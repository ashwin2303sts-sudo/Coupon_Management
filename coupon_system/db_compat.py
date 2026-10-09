from django.db.backends.mysql.features import DatabaseFeatures


def _minimum_database_version(self):
    return (5, 7)


DatabaseFeatures.minimum_database_version = property(_minimum_database_version)
DatabaseFeatures.can_return_columns_from_insert = property(lambda self: False)
DatabaseFeatures.can_return_rows_from_bulk_insert = property(lambda self: False)
