UPDATE configuration SET version = '0.7';

DROP VIEW builds_pending;
CREATE VIEW builds_pending AS
    SELECT
        v.package,
        v.version,
        a.abi_tag
    FROM
        packages AS p
        JOIN versions AS v
            ON v.package = p.package
        LEFT JOIN builds AS b
            ON  v.package = b.package
            AND v.version = b.version
        CROSS JOIN (
            SELECT MIN(abi_tag) AS abi_tag
            FROM build_abis
        ) AS a
    WHERE b.version IS NULL
    AND   NOT v.skip
    AND   NOT p.skip

    UNION ALL

    (
        SELECT
            p.package,
            p.version,
            b.abi_tag
        FROM
            (
                SELECT DISTINCT
                    b.package,
                    b.version
                FROM
                    builds AS b
                    JOIN files AS f
                        ON b.build_id = f.build_id
                WHERE f.abi_tag <> 'none'
            ) AS p
            CROSS JOIN build_abis AS b

        EXCEPT

        SELECT
            b.package,
            b.version,
            f.abi_tag
        FROM
            builds AS b
            JOIN files AS f
                ON b.build_id = f.build_id
        WHERE f.abi_tag <> 'none'
    );

GRANT SELECT ON builds_pending TO {username};
