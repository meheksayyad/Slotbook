"""btree_gist lets the exclusion constraint combine `court =` with a range overlap test."""
from django.contrib.postgres.operations import BtreeGistExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = []
    operations = [BtreeGistExtension()]
