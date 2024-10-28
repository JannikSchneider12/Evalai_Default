import json
import os
import time
from pathlib import Path
import sys

import requests

from eval_ai_interface import EvalAI_Interface
from evaluate import evaluate



#############################################################################
def load_config(file_path='github/host_config.json'):
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: {file_path} not found.")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: {file_path} is not a valid JSON file.")
        sys.exit(1)

# Load configuration from JSON file
config = load_config()


# Define mapping between config file keys and required variable names
config_mapping = {
    "token": "AUTH_TOKEN",
    "evalai_host_url": "API_SERVER",

    "queue_name": "QUEUE_NAME",
    "challenge_pk": "CHALLENGE_PK",
    "save_dir": "SAVE_DIR"
}

# Set environment variables from config
for config_key, env_var in config_mapping.items():
    if config_key in config:
        os.environ[env_var] = str(config[config_key])
    # elif env_var != "SAVE_DIR":  # SAVE_DIR is optional
    #     print(f"Error: {config_key} is not set in the config file.")
    #     sys.exit(1)
# Set default for SAVE_DIR if not in config
if "SAVE_DIR" not in os.environ:
    os.environ["SAVE_DIR"] = "./"

#############################################################################

# Remote Evaluation Meta Data
# See https://evalai.readthedocs.io/en/latest/evaluation_scripts.html#writing-remote-evaluation-script
auth_token = os.environ["AUTH_TOKEN"]
evalai_api_server = os.environ["API_SERVER"]
queue_name = "embed2scale-challenge-test2--2389-production-c43a1f6e-35a3-4e13-b1ef-14f7fa771e6"
challenge_pk = "2389" #os.environ["CHALLENGE_PK"]
save_dir = os.environ.get("SAVE_DIR", "./")


def download(submission, save_dir):
    response = requests.get(submission["input_file"])
    submission_file_path = os.path.join(
        save_dir, submission["input_file"].split("/")[-1]
    )
    with open(submission_file_path, "wb") as f:
        f.write(response.content)
    return submission_file_path


def update_running(evalai, submission_pk):
    status_data = {
        "submission": submission_pk,
        "submission_status": "RUNNING",
    }
    update_status = evalai.update_submission_status(status_data)


def update_failed(
    evalai, phase_pk, submission_pk, submission_error, stdout="", metadata=""
):
    submission_data = {
        "challenge_phase": phase_pk,
        "submission": submission_pk,
        "stdout": stdout,
        "stderr": submission_error,
        "submission_status": "FAILED",
        "metadata": metadata,
    }
    update_data = evalai.update_submission_data(submission_data)


def update_finished(
    evalai,
    phase_pk,
    submission_pk,
    result,
    submission_error="",
    stdout="",
    metadata="",
):
    submission_data = {
        "challenge_phase": phase_pk,
        "submission": submission_pk,
        "stdout": stdout,
        "stderr": submission_error,
        "submission_status": "FINISHED",
        "result": result,
        "metadata": metadata,
    }
    update_data = evalai.update_submission_data(submission_data)


if __name__ == "__main__":
    evalai = EvalAI_Interface(auth_token, evalai_api_server, queue_name, challenge_pk)

    while True:
        # Get the message from the queue
        message = evalai.get_message_from_sqs_queue()
        message_body = message.get("body")
        if message_body:
            submission_pk = message_body.get("submission_pk")
            challenge_pk = message_body.get("challenge_pk")
            phase_pk = message_body.get("phase_pk")
            # Get submission details -- This will contain the input file URL
            submission = evalai.get_submission_by_pk(submission_pk)
            challenge_phase = evalai.get_challenge_phase_by_pk(phase_pk)
            if (
                submission.get("status") == "finished"
                or submission.get("status") == "failed"
                or submission.get("status") == "cancelled"
            ):
                message_receipt_handle = message.get("receipt_handle")
                evalai.delete_message_from_sqs_queue(message_receipt_handle)

            else:
                if submission.get("status") == "submitted":
                    update_running(evalai, submission_pk)
                submission_file_path = download(submission, save_dir)
                try:
                    results = evaluate(
                        submission_file_path, challenge_phase["codename"]
                    )
                    update_finished(
                        evalai, phase_pk, submission_pk, json.dumps(results["result"])
                    )
                except Exception as e:
                    update_failed(evalai, phase_pk, submission_pk, str(e))
        # Poll challenge queue for new submissions
        time.sleep(60)
