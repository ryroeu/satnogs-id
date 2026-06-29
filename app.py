"""Gradio entrypoint for satnogs-id Identify (local or HF Space).
Run: docker compose run --rm --service-ports app python app.py
"""
from satnogs_id.service.app import build_identify_app

demo = build_identify_app()

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
