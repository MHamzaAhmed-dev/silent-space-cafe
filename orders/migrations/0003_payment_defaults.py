from django.db import migrations


def defaults(apps, schema_editor):
    Method = apps.get_model('orders', 'PaymentMethod')
    for code, values in [
        ('jazzcash', dict(delivery=True, pickup=True, dine_in=True, receiver='03249233487', instructions='Transfer the exact amount below, then submit your transaction reference. The cafe will verify your payment.', display_order=0)),
        ('easypaisa', dict(enabled=False, delivery=True, pickup=True, dine_in=True, display_order=1)),
        ('card', dict(enabled=False, delivery=True, pickup=True, dine_in=True, display_order=2)),
        ('cod', dict(delivery=True, display_order=3)),
        ('cash', dict(pickup=True, dine_in=True, display_order=4)),
    ]:
        Method.objects.get_or_create(code=code, defaults=values)


class Migration(migrations.Migration):
    dependencies = [('orders', '0002_paymentmethod_alter_dineinorder_options_and_more')]
    operations = [migrations.RunPython(defaults, migrations.RunPython.noop)]
