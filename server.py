from app.main import app as flask_app
import app.routes  # noqa: F401 - registers routes

# Expose as 'application' so gunicorn finds it unambiguously
# (avoids collision with the 'app' package directory)
application = flask_app

if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=5000, debug=False)
