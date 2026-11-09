import numpy as np
from sklearn.metrics import precision_score, recall_score, f1_score, mean_absolute_error, mean_squared_error, r2_score

def calculate_location_metrics(y_true, y_pred):
    intersection = np.logical_and(y_true, y_pred).sum()
    union = np.logical_or(y_true, y_pred).sum()
    iou = intersection / union if union > 0 else 0.0
    
    precision = precision_score(y_true.flatten(), y_pred.flatten(), zero_division=0)
    recall = recall_score(y_true.flatten(), y_pred.flatten(), zero_division=0)
    f1 = f1_score(y_true.flatten(), y_pred.flatten(), zero_division=0)
    
    return {'iou': round(iou, 4), 'precision': round(precision, 4), 'recall': round(recall, 4), 'f1_score': round(f1, 4)}

def calculate_magnitude_metrics(y_true, y_pred):
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    r2 = r2_score(y_true, y_pred) if len(y_true) > 1 else 0.0
    return {'mae': round(mae, 4), 'rmse': round(rmse, 4), 'r2': round(r2, 4)}