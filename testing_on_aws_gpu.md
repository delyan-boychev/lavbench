# Testing the Container Sandbox with AWS GPU Instances

This guide outlines how to cheaply and effectively test the sandboxed evaluation pipeline using an actual NVIDIA GPU on an AWS EC2 instance.

---

## 1. Launching a Cheap AWS GPU Instance

1. Log into your **AWS Management Console**.
2. Navigate to **EC2** -> **Launch Instance**.
3. Choose the **Deep Learning AMI GPU PyTorch** (e.g., Ubuntu 22.04) as the machine image (AMI). This image pre-packages CUDA, Nvidia Drivers, and Docker.
4. Select instance type: **`g4dn.xlarge`** (contains 1 NVIDIA T4 GPU).
   * *Tip*: In the **Advanced Details** section, check **Request Spot Instances**. Spot instances bring the hourly cost down from ~$0.52 to **~$0.15/hour**.
5. Set up your Key Pair, enable SSH access, and launch the instance.

---

## 2. Setting Up the NVIDIA Container Toolkit

If you start with a clean Ubuntu server instead of a Deep Learning AMI, or need to ensure Docker has GPU capabilities enabled, SSH into the instance and run:

```bash
# 1. Add NVIDIA Container Toolkit repository
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
  && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

# 2. Install the toolkit
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

# 3. Restart the Docker daemon to apply changes
sudo systemctl restart docker
```

To verify that Docker can access the GPU, run:
```bash
docker run --rm --gpus all nvidia/cuda:11.0.3-base-ubuntu20.04 nvidia-smi
```
*(If this outputs the Nvidia GPU table, Docker is ready).*

---

## 3. Configuring `test_run.py` for GPU Testing

To run a real container execution on the GPU instead of the mock Docker CLI, make the following edits to the [test_run.py](file:///Users/delyan-boychev/nai-webplatform/test_run.py) script:

### Edit A: Disable Mock PATH Prepending
Comment out the lines at the top of the `main()` function in `test_run.py` that override the system `PATH`:
```python
# MOCK_BIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'mock_bin'))
# os.environ["PATH"] = f"{MOCK_BIN_DIR}{os.path.pathsep}{os.environ.get('PATH', '')}"
```

### Edit B: Update Task Specs
Locate the `Task` creation block and set the GPU options:
```python
task = Task(
    challenge_id=challenge.id,
    title="Container Verification Task",
    description="Solve this task using a predict function using numpy.",
    ram_limit_mb=2048,
    time_limit_sec=15,
    gpu_required=True,  # Set this to True
    files="[]",
    evaluator_script_path=evaluator_path,
    public_eval_percentage=50,
    base_docker_image="pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime", # GPU Image
    apt_packages="curl",
    pip_requirements="numpy>=1.20.0"
)
```

### Edit C: Update the Solution to Verify CUDA
Modify the `solution_code` to import PyTorch and log CUDA device information:
```python
solution_code = [
    "# SUBMIT",
    "import torch",
    "def predict(inputs):",
    "    print('--- CONTAINER CUDA DIAGNOSTICS ---')",
    "    print('CUDA Available:', torch.cuda.is_available())",
    "    if torch.cuda.is_available():",
    "        print('Device Name:', torch.cuda.get_device_name(0))",
    "    return [1] * len(inputs)"
]
```

---

## 4. Executing the GPU Test

Activate the virtual environment and launch `test_run.py` while explicitly pinning the evaluation to GPU device ID `0`:

```bash
WORKER_GPU_ID=0 venv/bin/python3 test_run.py
```

---

## 5. Reviewing the Results

When the script finishes, check the printed **Sandbox Execution Logs**. You should see:
1. Docker successfully building the PyTorch-based custom task image.
2. The docker execution command containing the `--gpus device=0` parameter:
   ```bash
   Executing sandbox command: docker run --rm --network none --pids-limit 64 --tmpfs /tmp -m 2048m -v ... --gpus device=0 ...
   ```
3. The diagnostics outputting `CUDA Available: True` and printing `Tesla T4` (or your specific GPU).
