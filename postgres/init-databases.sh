#!/bin/bash
set -e

echo "Starting database initialization..."

# Wait for PostgreSQL to be ready
until pg_isready -h postgres -p 5432 -U program; do
  echo "Waiting for PostgreSQL to be ready..."
  sleep 2
done

echo "PostgreSQL is ready, creating databases..."

# Create databases
psql -v ON_ERROR_STOP=1 -h postgres -U program -d postgres <<-EOSQL
    CREATE DATABASE cars;
    CREATE DATABASE rentals;
    CREATE DATABASE payments;
    GRANT ALL PRIVILEGES ON DATABASE cars TO program;
    GRANT ALL PRIVILEGES ON DATABASE rentals TO program;
    GRANT ALL PRIVILEGES ON DATABASE payments TO program;
EOSQL

echo "Databases created successfully"

# Create cars schema and insert data
psql -v ON_ERROR_STOP=1 -h postgres -U program -d cars <<-EOSQL
    CREATE TABLE cars
    (
        id                  SERIAL PRIMARY KEY,
        car_uid             uuid UNIQUE NOT NULL,
        brand               VARCHAR(80) NOT NULL,
        model               VARCHAR(80) NOT NULL,
        registration_number VARCHAR(20) NOT NULL,
        power               INT,
        price               INT         NOT NULL,
        type                VARCHAR(20)
            CHECK (type IN ('SEDAN', 'SUV', 'MINIVAN', 'ROADSTER')),
        availability        BOOLEAN     NOT NULL DEFAULT TRUE
    );

    GRANT USAGE, SELECT ON SEQUENCE cars_id_seq TO program;
    GRANT ALL PRIVILEGES ON TABLE cars TO program;

    INSERT INTO cars (car_uid, brand, model, registration_number, power, price, type, availability) VALUES
    ('109b42f3-198d-4c89-9276-a7520a7120ab', 'Mercedes Benz', 'GLA 250', 'ЛО777Х799', 249, 3500, 'SEDAN', true),
    ('209b42f3-198d-4c89-9276-a7520a7120ab', 'BMW', 'X5', 'А123БВ777', 300, 5000, 'SUV', true),
    ('309b42f3-198d-4c89-9276-a7520a7120ab', 'Audi', 'A4', 'В456ГД777', 200, 4000, 'SEDAN', true);
EOSQL

echo "Cars schema and data created successfully"

# Create rentals schema
psql -v ON_ERROR_STOP=1 -h postgres -U program -d rentals <<-EOSQL
    CREATE TABLE rental
    (
        id          SERIAL PRIMARY KEY,
        rental_uid  uuid UNIQUE NOT NULL,
        username    VARCHAR(80) NOT NULL,
        payment_uid uuid        NOT NULL,
        car_uid     uuid        NOT NULL,
        date_from   TIMESTAMP   NOT NULL,
        date_to     TIMESTAMP   NOT NULL,
        status      VARCHAR(20) NOT NULL DEFAULT 'IN_PROGRESS'
    );

    GRANT USAGE, SELECT ON SEQUENCE rental_id_seq TO program;
    GRANT ALL PRIVILEGES ON TABLE rental TO program;
EOSQL

echo "Rentals schema created successfully"

# Create payments schema
psql -v ON_ERROR_STOP=1 -h postgres -U program -d payments <<-EOSQL
    CREATE TABLE payment
    (
        id          SERIAL PRIMARY KEY,
        payment_uid uuid UNIQUE NOT NULL,
        status      VARCHAR(20) NOT NULL,
        price       INT         NOT NULL
    );

    GRANT USAGE, SELECT ON SEQUENCE payment_id_seq TO program;
    GRANT ALL PRIVILEGES ON TABLE payment TO program;
EOSQL

echo "Payments schema created successfully"
echo "Database initialization completed!"

