from datetime import datetime, timezone

from flask import Flask, jsonify, request


app = Flask(__name__)


@app.post("/callback")
def callback():
    payload = request.get_json(silent=True) or {}
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    print(f"[CALLBACK] {now} payload={payload}")
    return jsonify({"message": "callback received"}), 200


@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7001, debug=False)
