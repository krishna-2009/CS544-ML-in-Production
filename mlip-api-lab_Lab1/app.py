import os

from dotenv import load_dotenv

# Load environment variables from .env file into os.environ
load_dotenv()

from flask import Flask, jsonify, render_template, request

from analyze import ModelOutputError, get_itinerary

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/v1/itinerary")
def itinerary():
    destination = request.args.get("destination", "").strip()

    # Basic request validation
    if not destination:
        return jsonify({"error": "Missing required query parameter: destination"}), 400
    if len(destination) > 120:
        return jsonify({"error": "destination is too long (max 120 chars)"}), 400

    try:
        result = get_itinerary(destination)
        return jsonify(result), 200
    except ModelOutputError as e:
        # Model responded but broke the schema — upstream problem, not the caller's.
        return jsonify({"error": f"Failed to generate itinerary: {e}"}), 502
    except ValueError as e:
        # Client-side input errors / missing config
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        # Upstream/model errors
        return jsonify({"error": f"Failed to generate itinerary: {e}"}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)