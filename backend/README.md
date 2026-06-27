# LavBench Backend

Flask + Celery backend for the LavBench sandboxed code evaluation platform.

## Development

```bash
pip install -r requirements.txt -r dev-requirements.txt
python app.py
```

## Testing

```bash
python -m pytest tests/ -n auto -v --cov=.
```

## Docker

```bash
docker build -t lavbench-backend .
```
