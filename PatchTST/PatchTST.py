import pandas as pd
import numpy as np
import glob
import warnings
import torch
from pathlib import Path
from sklearn.preprocessing import StandardScaler, RobustScaler
from tsfm_public.toolkit.dataset import ForecastDFDataset
from models.ForecastDFDataset import ForecastDFDataset
from transformers import (
    EarlyStoppingCallback,
    PatchTSTConfig,
    PatchTSTForPrediction,
    set_seed,
    Trainer,
    TrainingArguments
)
from sklearn.metrics import mean_squared_error

# Ignore Torch Warnings.
warnings.filterwarnings("ignore", module="torch")
set_seed(2023)  # Set Seed for Reproducibility.

# Paths for log and model
log_path = "Data/Log/"  # Path to Log
model_path = "Data/Model/"  # Path to Model

# Create Log and Model directories if they don't exist
Path(log_path).mkdir(parents=True, exist_ok=True)
Path(model_path).mkdir(parents=True, exist_ok=True)

# Hyperparameters with smaller windows
context_length = 512  # Reduced Context Length
forecast_horizon = 96  # Reduced Forecast Horizon
patch_length = 32  # Reduced Patch Length
num_workers = 8  # Number of Workers
batch_size = 8  # Increased Batch Size

# Input parameters
timestamp_column = "date"  # Preset the timestamp column
csv_files = glob.glob("../data/ETTh1.csv")
delimiter = ","
index_start = 1
resume_from_checkpoint = False

# Read CSV Files
dataframes = [pd.read_csv(f, delimiter=delimiter, parse_dates=[timestamp_column]) for f in csv_files]
dataset = pd.concat(dataframes, ignore_index=True)

# Preprocessing: Remove outliers using IQR and fill missing values
numeric_columns = dataset.select_dtypes(include=[np.number]).columns  # Select only numeric columns
Q1 = dataset[numeric_columns].quantile(0.25)
Q3 = dataset[numeric_columns].quantile(0.75)
IQR = Q3 - Q1

# Remove outliers
dataset = dataset[~((dataset[numeric_columns] < (Q1 - 1.5 * IQR)) | (dataset[numeric_columns] > (Q3 + 1.5 * IQR))).any(axis=1)]

# Fill missing values generated by lag/rolling calculations
dataset.ffill(inplace=True)
dataset.bfill(inplace=True)

# Feature Engineering: adding time-based features and casting them to float32 immediately
dataset["day_of_week"] = dataset[timestamp_column].dt.dayofweek.astype(np.float32)
dataset["day_of_month"] = dataset[timestamp_column].dt.day.astype(np.float32)
dataset["month"] = dataset[timestamp_column].dt.month.astype(np.float32)
dataset["hour"] = dataset[timestamp_column].dt.hour.astype(np.float32)

# Scale the dataset using StandardScaler or RobustScaler
scaler = RobustScaler()
scaled_values = scaler.fit_transform(dataset.iloc[:, index_start:])

# Ensure the columns are compatible with the scaled values (i.e., float32)
dataset.iloc[:, index_start:] = dataset.iloc[:, index_start:].astype(np.float32)

# Assign the scaled values (which are also float32)
dataset.iloc[:, index_start:] = scaled_values.astype(np.float32)

# Adding Lag Features and Rolling Statistics (Feature Engineering)
for col in dataset.columns[index_start:]:
    dataset[f'{col}_lag1'] = dataset[col].shift(1)
    dataset[f'{col}_rolling_mean'] = dataset[col].rolling(window=5).mean()
    dataset[f'{col}_rolling_std'] = dataset[col].rolling(window=5).std()

# Fill missing values generated by lag/rolling calculations
dataset.ffill(inplace=True)
dataset.bfill(inplace=True)

# Splitting the dataset
num_train = int(len(dataset) * 0.7)  # 70% Train
num_test = int(len(dataset) * 0.2)   # 20% Test
num_valid = len(dataset) - num_train - num_test  # 10% Valid

# Define train, validation, and test datasets
train_dataset = dataset.iloc[:num_train].reset_index(drop=True)
valid_dataset = dataset.iloc[num_train:num_train + num_valid].reset_index(drop=True)
test_dataset = dataset.iloc[num_train + num_valid:].reset_index(drop=True)

# Creating ForecastDFDataset instances after preprocessing
train_dataset = ForecastDFDataset(
    data_df=train_dataset,
    timestamp_column=timestamp_column,
    target_columns=dataset.columns[index_start:],  # Including new features
    context_length=context_length,
    prediction_length=forecast_horizon
)

valid_dataset = ForecastDFDataset(
    data_df=valid_dataset,
    timestamp_column=timestamp_column,
    target_columns=dataset.columns[index_start:],  # Including new features
    context_length=context_length,
    prediction_length=forecast_horizon
)

test_dataset = ForecastDFDataset(
    data_df=test_dataset,
    timestamp_column=timestamp_column,
    target_columns=dataset.columns[index_start:],  # Including new features
    context_length=context_length,
    prediction_length=forecast_horizon
)

# Config for PatchTST with optimized hyperparameters
config = PatchTSTConfig(
    num_input_channels=len(dataset.columns[index_start:]),  # Increased input channels
    context_length=context_length,
    patch_length=patch_length,
    patch_stride=patch_length,
    prediction_length=forecast_horizon,
    random_mask_ratio=0.4,
    d_model=256,  # Increased model capacity
    num_attention_heads=8,
    num_hidden_layers=6,  # Increased layers
    ffn_dim=1024,  # Increased FFN size
    dropout=0.2,
    head_dropout=0.2,
    pooling_type=None,
    channel_attention=True,  # Enable channel attention
    scaling="standard",
    loss="mse",
    pre_norm=True,
    norm_type="layernorm",  # Use LayerNorm for better stability
)

# Initialize the model
model = PatchTSTForPrediction(config)

# Check if GPU (CUDA) is available and set the device accordingly
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {device}")

# Ensure the model is moved to the GPU (if available)
model.to(device)


# Training Arguments with adjusted epochs and learning rate
training_args = TrainingArguments(
    output_dir=model_path,
    overwrite_output_dir=True,
    num_train_epochs=400,  # Increased epochs for longer training
    learning_rate=5e-6,  # Further lower learning rate for stability
    weight_decay=0.01,  # Added weight decay for regularization
    do_eval=True,
    eval_strategy="epoch",
    per_device_train_batch_size=batch_size,
    per_device_eval_batch_size=batch_size,
    dataloader_num_workers=num_workers,
    save_strategy="epoch",
    logging_strategy="epoch",
    save_total_limit=3,
    logging_dir=log_path,
    load_best_model_at_end=True,
    metric_for_best_model="eval_loss",
    greater_is_better=False,
    label_names=["future_values"],
)

# Create the early stopping callback with more patience
early_stopping_callback = EarlyStoppingCallback(
    early_stopping_patience=20,
    early_stopping_threshold=0.0001,
)

# Define trainer
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=valid_dataset,
    callbacks=[early_stopping_callback]
)

# Train the model
trainer.train()

# After training, evaluate the model on the test dataset to get predictions
predictions_tuple = trainer.predict(test_dataset)

# Unpack the predictions, label_ids (true_values), and metrics
predictions, label_ids, metrics = predictions_tuple

# If predictions come as a list, ensure they are converted to an array
if isinstance(predictions, (list, tuple)):
    predictions = predictions[0]  # Extract predictions if they are nested in a tuple/list

# Flatten the predicted values and true values for comparison
predicted_values = predictions.flatten()
true_values = label_ids.flatten()

# Calculate the MSE
mse = mean_squared_error(true_values, predicted_values)

# Print the final MSE
print(f"Final Mean Squared Error (MSE): {mse}")

