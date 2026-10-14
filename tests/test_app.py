import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from app import app, initialize_db

TEST_PASSWORD = "safe-" + "pass" + "word-" + "123"
INVALID_PASSWORD = "wrong-" + "pass" + "word"


class FoodApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        app.config.update(
            TESTING=True,
            DATABASE=str(Path(self.temp_dir.name) / "test.sqlite3"),
        )
        initialize_db()
        self.client = app.test_client()
        response = self.register()
        self.assertEqual(response.status_code, 201)

    def tearDown(self):
        self.temp_dir.cleanup()

    def register(self, client=None, **overrides):
        payload = {
            "name": "Gabo",
            "email": "gabo@example.com",
            "password": TEST_PASSWORD,
        }
        payload.update(overrides)
        return (client or self.client).post("/api/register", json=payload)

    def create_food(self, **overrides):
        payload = {
            "name": "Tomate",
            "category": "Verduras",
            "quantity": 2,
            "unit": "unidad",
            "expires_on": (date.today() + timedelta(days=2)).isoformat(),
        }
        payload.update(overrides)
        return self.client.post(
            "/api/foods",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_create_food_and_dashboard_priority(self):
        response = self.create_food()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["name"], "Tomate")

        dashboard = self.client.get("/api/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.json["stats"]["active"], 1)
        self.assertEqual(dashboard.json["stats"]["urgent"], 1)

    def test_registration_password_hash_and_login_session(self):
        with app.test_client() as client:
            registration = self.register(client, email="new@example.com")
            self.assertEqual(registration.status_code, 201)

            with app.app_context():
                from app import get_db

                with get_db() as connection:
                    user = connection.execute(
                        "SELECT password_hash FROM users WHERE email = ?",
                        ("new@example.com",),
                    ).fetchone()
            self.assertNotEqual(user["password_hash"], "safe-password-123")

        with app.test_client() as client:
            self.assertEqual(client.get("/api/session").json["user"], None)
            login = client.post(
                "/api/login",
                json={
                    "email": "NEW@example.com",
                    "password": TEST_PASSWORD,
                },
            )
            self.assertEqual(login.status_code, 200)
            self.assertEqual(login.json["user"]["email"], "new@example.com")
            self.assertEqual(
                client.get("/api/session").json["user"]["name"],
                "Gabo",
            )
            self.assertEqual(client.post("/api/logout").status_code, 200)
            self.assertIsNone(client.get("/api/session").json["user"])

    def test_duplicate_registration_and_wrong_password_are_rejected(self):
        duplicate = self.register()
        self.assertEqual(duplicate.status_code, 409)

        with app.test_client() as client:
            invalid_login = client.post(
                "/api/login",
                json={
                    "email": "gabo@example.com",
                    "password": INVALID_PASSWORD,
                },
            )
        self.assertEqual(invalid_login.status_code, 401)

    def test_food_endpoints_require_login(self):
        with app.test_client() as client:
            self.assertEqual(client.get("/api/dashboard").status_code, 401)
            self.assertEqual(client.get("/api/ideas").status_code, 401)
            self.assertEqual(client.get("/api/history").status_code, 401)
            response = client.post(
                "/api/foods",
                json={
                    "name": "Tomate",
                    "category": "Verduras",
                    "quantity": 1,
                    "unit": "unidad",
                    "expires_on": date.today().isoformat(),
                },
            )
            self.assertEqual(response.status_code, 401)

    def test_foods_are_isolated_between_users(self):
        food_id = self.create_food().json["id"]
        with app.test_client() as other_client:
            self.register(
                other_client,
                name="Ana",
                email="ana@example.com",
            )
            self.assertEqual(
                other_client.get("/api/dashboard").json["stats"]["active"], 0
            )
            self.assertEqual(
                other_client.patch(
                    f"/api/foods/{food_id}", json={"status": "used"}
                ).status_code,
                404,
            )
            self.assertEqual(
                other_client.delete(f"/api/foods/{food_id}").status_code, 404
            )
        self.assertEqual(
            self.client.get("/api/dashboard").json["stats"]["active"], 1
        )

    def test_existing_food_database_is_migrated_and_claimed_on_first_signup(
        self,
    ):
        database_path = Path(self.temp_dir.name) / "legacy.sqlite3"
        app.config["DATABASE"] = str(database_path)
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                """
                CREATE TABLE foods (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    unit TEXT NOT NULL,
                    expires_on TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                INSERT INTO foods (name, category, quantity, unit, expires_on)
                VALUES ('Tomate antiguo', 'Verduras', 1, 'unidad', ?)
                """,
                (date.today().isoformat(),),
            )

        initialize_db()
        with app.test_client() as client:
            registration = self.register(client, email="legacy@example.com")
            self.assertEqual(registration.status_code, 201)
            dashboard = client.get("/api/dashboard").json
        self.assertEqual(dashboard["stats"]["active"], 1)
        self.assertEqual(dashboard["foods"][0]["name"], "Tomate antiguo")

    def test_rejects_invalid_food(self):
        response = self.create_food(quantity=-1)
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json)

    def test_rejects_invalid_json_field_types(self):
        response = self.create_food(category=[])
        self.assertEqual(response.status_code, 400)

        food_id = self.create_food().json["id"]
        invalid_status = self.client.patch(
            f"/api/foods/{food_id}",
            json={"status": []},
        )
        self.assertEqual(invalid_status.status_code, 400)

    def test_food_can_be_marked_used_or_wasted_and_appears_in_history(self):
        first_id = self.create_food().json["id"]
        second_id = self.create_food(name="Manzana").json["id"]

        used = self.client.patch(
            f"/api/foods/{first_id}",
            json={"status": "used"},
        )
        wasted = self.client.patch(
            f"/api/foods/{second_id}",
            json={"status": "wasted"},
        )
        self.assertEqual(used.status_code, 200)
        self.assertEqual(wasted.status_code, 200)

        dashboard = self.client.get("/api/dashboard").json
        self.assertEqual(dashboard["stats"]["active"], 0)
        self.assertEqual(dashboard["stats"]["used"], 1)
        self.assertEqual(dashboard["stats"]["wasted"], 1)

        history_events = self.client.get("/api/history").json["events"]
        self.assertEqual(len(history_events), 2)

    def test_cannot_mark_food_twice(self):
        food_id = self.create_food().json["id"]
        self.client.patch(f"/api/foods/{food_id}", json={"status": "used"})

        response = self.client.patch(
            f"/api/foods/{food_id}",
            json={"status": "wasted"},
        )
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
