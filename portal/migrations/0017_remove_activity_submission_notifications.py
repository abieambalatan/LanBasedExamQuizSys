from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("portal", "0016_activity_submission_notifications"),
    ]

    operations = [
        migrations.DeleteModel(
            name="ActivitySubmissionNotification",
        ),
    ]
