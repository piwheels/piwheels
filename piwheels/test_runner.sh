export PW_DB=test_piwheels
export PW_USER=piwheels
export PW_HOST=localhost
export PW_PASS=piwheels
export PW_NUM=1
cat piwheels.sql | psql $PW_DB
python3 tests.py
