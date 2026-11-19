import os

MAINT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maintenance_on.txt")


def _maintenance_setting():
    from app import MaintenanceSetting, db

    return db.session.get(MaintenanceSetting, 1)


def is_maintenance_on():
    setting = _maintenance_setting()
    if setting is not None:
        return setting.enabled
    return os.path.exists(MAINT_FILE)


def turn_on_maintenance():
    set_maintenance(True)


def turn_off_maintenance():
    set_maintenance(False)


def set_maintenance(enabled):
    from app import MaintenanceSetting, db

    setting = _maintenance_setting()
    if setting is None:
        setting = MaintenanceSetting(id=1, enabled=bool(enabled))
        db.session.add(setting)
    else:
        setting.enabled = bool(enabled)
    db.session.commit()