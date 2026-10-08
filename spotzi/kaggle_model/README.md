# Own model trained on Kaggle data

Dataset: **Healthcare Provider Fraud Detection Analysis** (Kaggle: `rohitrox/healthcare-provider-fraud-detection-analysis`),
public Medicare-style beneficiary / inpatient / outpatient claims with a provider-level `PotentialFraud` label.

## 1. Get the data (needs your Kaggle account)
```bash
# put your token at ~/.kaggle/kaggle.json (Kaggle → Settings → API → Create New Token), then:
chmod 600 ~/.kaggle/kaggle.json
cd spotzi
kaggle datasets download -d rohitrox/healthcare-provider-fraud-detection-analysis -p data/kaggle --unzip
```
Expected files in `data/kaggle/`: `Train_Beneficiarydata*.csv`, `Train_Inpatientdata*.csv`, `Train_Outpatientdata*.csv`, `Train*.csv` (labels: Provider, PotentialFraud).

## 2. Train
```bash
python3 kaggle_model/train.py          # writes kaggle_model/model.joblib + metrics.json
```
## 3. Use
Restart `server.py`: if `model.joblib` exists, every provider gets an "own-model" probability (provider page, explorer, case brief, governance model card).

Transfer caveat: the model learns *relative* behaviour (percentile of claims-per-beneficiary, amount spread, repeat-beneficiary share, inpatient share, etc.) on real-style Medicare claims, then scores our synthetic providers on the same relative features. It is a complementary signal, not ground truth.
