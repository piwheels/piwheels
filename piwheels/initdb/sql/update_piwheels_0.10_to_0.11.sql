UPDATE configuration SET version = '0.11';

CREATE VIEW downloads_recent AS
SELECT
    p.package,
    COUNT(*) AS downloads
FROM
    packages AS p
    LEFT JOIN (
        builds AS b
        JOIN files AS f ON b.build_id = f.build_id
        JOIN downloads AS d ON d.filename = f.filename
    ) ON p.package = b.package
WHERE
    d.accessed_at IS NULL
    OR d.accessed_at > CURRENT_TIMESTAMP - INTERVAL '1 month'
GROUP BY p.package;

GRANT SELECT ON downloads_recent TO {username};

COMMIT;
