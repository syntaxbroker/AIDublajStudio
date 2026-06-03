def test_health_endpoints(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    db_response = client.get("/health/db")
    assert db_response.status_code == 200
    assert db_response.json()["dependency"] == "db"

    redis_response = client.get("/health/redis")
    assert redis_response.status_code == 200
    assert redis_response.json()["dependency"] == "redis"
