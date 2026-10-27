def test_register_user_success(client):
    response = client.post("/user/", json={
        "email": "newuser@example.com",
        "name": "New User",
        "password": "Password123"
    })
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@example.com"
    assert data["name"] == "New User"
    assert data["active"] is False


def test_register_duplicate_email(client, test_user):
    response = client.post("/user/", json={
        "email": test_user.email,
        "name": "Duplicate User",
        "password": "Password123"
    })
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_verify_otp_flow(client, db_session):
    from app import model
    # Register user
    client.post("/user/", json={
        "email": "otpuser@example.com",
        "name": "OTP User",
        "password": "Password123"
    })

    # Fetch OTP from DB
    user = db_session.query(model.Users).filter(model.Users.email == "otpuser@example.com").first()
    assert user is not None
    otp = user.verification_otp

    # Verify with correct OTP
    verify_res = client.post("/user/verify-otp", json={
        "email": "otpuser@example.com",
        "otp": otp
    })
    assert verify_res.status_code == 200
    assert "verified successfully" in verify_res.json()["message"]

    # Check user is active
    db_session.refresh(user)
    assert user.active is True


def test_login_success(client, test_user):
    response = client.post("/login", data={
        "username": test_user.email,
        "password": "password123"
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_invalid_password(client, test_user):
    response = client.post("/login", data={
        "username": test_user.email,
        "password": "wrongpassword"
    })
    assert response.status_code == 401


def test_get_current_user_profile(client, auth_headers, test_user):
    response = client.get("/user/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == test_user.email
    assert data["name"] == test_user.name


def test_malformed_token_sub_returns_401(client):
    from jose import jwt
    from app.config import settings

    # Token with non-numeric sub
    bad_token = jwt.encode({"sub": "not_an_int"}, settings.secret_key, algorithm=settings.algorithm)
    response = client.get("/user/me", headers={"Authorization": f"Bearer {bad_token}"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


def test_logout_revokes_token(client, auth_headers):
    # Verify token works
    res_before = client.get("/user/me", headers=auth_headers)
    assert res_before.status_code == 200

    # Call logout
    logout_res = client.post("/logout", headers=auth_headers)
    assert logout_res.status_code == 200

    # Old token should now be rejected
    res_after = client.get("/user/me", headers=auth_headers)
    assert res_after.status_code == 401


def test_legacy_token_without_version_rejected(client, test_user):
    from jose import jwt
    from app.config import settings

    # Token signed without 'ver' claim
    token_without_ver = jwt.encode(
        {"sub": str(test_user.id)},
        settings.secret_key,
        algorithm=settings.algorithm
    )
    res = client.get("/user/me", headers={"Authorization": f"Bearer {token_without_ver}"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Could not validate credentials"

