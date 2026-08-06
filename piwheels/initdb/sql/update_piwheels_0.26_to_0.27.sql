UPDATE configuration SET version = '0.27';

DROP FUNCTION log_search(
  TEXT, INET, TIMESTAMP,
  TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
);

DROP TABLE searches;
