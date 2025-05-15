CREATE OR REPLACE FUNCTION backup_enrollment_before_delete_func()
RETURNS trigger AS $$
BEGIN
    INSERT INTO deleted_enrollments (student_id, course_id, deleted_at)
    VALUES (OLD.student_id, OLD.course_id, NOW());
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'backup_enrollment_before_delete'
    ) THEN
        CREATE TRIGGER backup_enrollment_before_delete
        BEFORE DELETE ON enrollment
        FOR EACH ROW
        EXECUTE FUNCTION backup_enrollment_before_delete_func();
    END IF;
END $$;

CREATE OR REPLACE FUNCTION remove_backup_after_restore_func()
RETURNS trigger AS $$
BEGIN
    DELETE FROM deleted_enrollments
    WHERE student_id = NEW.student_id AND course_id = NEW.course_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'remove_backup_after_restore'
    ) THEN
        CREATE TRIGGER remove_backup_after_restore
        AFTER INSERT ON enrollment
        FOR EACH ROW
        EXECUTE FUNCTION remove_backup_after_restore_func();
    END IF;
END $$;

SELECT* FROM deleted_enrollments

