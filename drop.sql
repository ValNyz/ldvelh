-- Supprimer toutes les tables, fonctions, types, vues
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;

-- Réappliquer les grants par défaut
GRANT ALL ON SCHEMA public TO postgres;
GRANT ALL ON SCHEMA public TO public;
