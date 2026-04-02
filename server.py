from app.main import app
import app.routes  # noqa: F401 - registers routes

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
