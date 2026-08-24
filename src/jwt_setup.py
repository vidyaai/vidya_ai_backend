import jwt, datetime
now = datetime.datetime.now(datetime.timezone.utc)
token = jwt.encode({
    "sub": "student-1",
    "name": "Test Student",
    "email": "student1@xyzlearn.com",
    "iss": "xyz_learn",
    "aud": "vidyaai-embed",
    "iat": now,
    "exp": now + datetime.timedelta(minutes=50),
}, "KDlKn4iinax__79-R03gRtYJsOZtfOFxiiiUwD2aM3g", algorithm="HS256")
print(token)
