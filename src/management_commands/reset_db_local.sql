DROP DATABASE vidyaai;
CREATE DATABASE vidyaai;
GRANT ALL PRIVILEGES ON DATABASE vidyaai TO vidyaidbuser;
\c vidyaai
GRANT ALL ON SCHEMA public TO vidyaidbuser;
\q