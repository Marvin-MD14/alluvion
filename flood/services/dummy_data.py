"""
Synthetic (DUMMY) Sentinel-1 style rasters para sa Tumana, Marikina - PARA SA TESTING/DEMO LAMANG.
Hindi ito totoong SAR data. Ang bawat imagery type ay may sariling noise/urban-masking para
magkaiba ang resulta ng comparison (VH > VV > SAR Urban), katulad ng inaasahan sa thesis.
"""
import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from scipy import ndimage

# Study area (Brgy. Tumana, Marikina) - approximate bounding box
WEST, EAST = 121.0900, 121.1020
SOUTH, NORTH = 14.6550, 14.6670
SIZE = 200  # 200 x 200 pixels (~6.6 m/pixel; demo resolution lang)
TRANSFORM = from_origin(WEST, NORTH, (EAST - WEST) / SIZE, (NORTH - SOUTH) / SIZE)

# (water_mean, water_std, land_mean, land_std, urban_mean, urban_std, urban_mask_prob)  in dB
TYPE_PARAMS = {
    'VH_LINEAR': (-24.0, 1.9, -17.0, 2.3, -12.0, 2.5, 0.20),
    'VH_GAMMA':  (-24.0, 1.7, -17.0, 2.1, -12.0, 2.3, 0.18),
    'VV_LINEAR': (-20.5, 2.6, -11.5, 2.6, -7.5, 2.8, 0.30),
    'VV_GAMMA':  (-20.5, 2.4, -11.5, 2.4, -7.5, 2.6, 0.28),
    'SAR_URBAN': (-21.0, 3.0, -14.0, 3.0, -8.0, 3.0, 0.55),
}
LINEAR_TYPES = ('VH_LINEAR', 'VV_LINEAR')


def _smooth_field(rng, sigma):
    f = ndimage.gaussian_filter(rng.normal(size=(SIZE, SIZE)), sigma)
    return (f - f.mean()) / f.std()


def valid_area():
    """False sa isang sulok (parang edge ng Sentinel-1 swath) - para ma-test ang nodata handling."""
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    return ~((xx + yy) < 14)


def make_truth(severity, seed):
    """Reference flood extent (bool) - floodplain sa paligid ng Marikina River."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE] / SIZE
    river_x = 0.52 + 0.10 * np.sin(2 * np.pi * yy * 1.3 + 0.8)
    d = np.abs(xx - river_x)
    field = _smooth_field(rng, 11)
    half_width = 0.025 + severity * 0.17 + 0.06 * field
    return ((d < half_width) & valid_area())


def urban_mask(seed=7):
    rng = np.random.default_rng(seed)
    f = _smooth_field(rng, 5)
    return f > 0.35


def make_sar(truth, code, seed):
    """Returns (array, nodata, is_linear). Flooded + urban pixels ay minsan 'nakatago' (double bounce)."""
    wm, ws, lm, ls, um, us, mask_p = TYPE_PARAMS[code]
    rng = np.random.default_rng(seed)
    urban = urban_mask()
    land = np.where(urban, rng.normal(um, us, truth.shape), rng.normal(lm, ls, truth.shape))
    water = rng.normal(wm, ws, truth.shape)
    hidden = truth & urban & (rng.random(truth.shape) < mask_p * 2.2)  # double-bounce sa flooded urban
    flooded_signal = truth & ~hidden
    db = np.where(flooded_signal, water, land)
    ok = valid_area()
    if code in LINEAR_TYPES:
        arr = np.power(10.0, db / 10.0).astype('float32')
        arr[~ok] = 0.0
        return arr, 0.0, True
    arr = db.astype('float32')
    arr[~ok] = -9999.0
    return arr, -9999.0, False


def geotiff_bytes(arr, nodata):
    profile = {
        'driver': 'GTiff', 'height': SIZE, 'width': SIZE, 'count': 1, 'dtype': 'float32',
        'crs': 'EPSG:4326', 'transform': TRANSFORM, 'nodata': nodata, 'compress': 'deflate',
    }
    with MemoryFile() as mem:
        with mem.open(**profile) as dst:
            dst.write(arr, 1)
        return mem.read()


# Dummy drainage outlets (name, lat, lon, elevation m) - hindi totoong survey data
DUMMY_OUTLETS = [
    ('Outlet T-01 Rizal St. (DUMMY)', 14.6662, 121.0958, 17.8),
    ('Outlet T-02 Tumana Creek (DUMMY)', 14.6641, 121.0985, 16.9),
    ('Outlet T-03 Bayan-Bayanan (DUMMY)', 14.6618, 121.0944, 18.4),
    ('Outlet T-04 Malanday Rd. (DUMMY)', 14.6593, 121.0971, 16.2),
    ('Outlet T-05 Riverbank (DUMMY)', 14.6574, 121.0997, 15.7),
    ('Outlet T-06 Concepcion Rd. (DUMMY)', 14.6560, 121.0930, 19.1),
]
