"""Helpers for current booking widgets in the reusable browser checks."""


def choose_booking_time(page, date, *, guests='2', zone='quiet', value='11:00', javascript=True, unavailable=False):
    page.locator('#id_date').fill(date.isoformat())
    page.locator('#id_guests').select_option(str(guests))
    page.locator('#id_zone').select_option(zone)
    if javascript:
        page.wait_for_function('document.querySelector("#id_time").options.length > 1 && !document.querySelector("#id_time").disabled')
    else:
        page.get_by_role('button', name='Check available times', exact=True).click()
    if unavailable:
        # Deliberately tamper a time to exercise server-side closed-hour validation.
        page.locator('#id_time').evaluate('(el, value) => el.add(new Option(value, value))', value)
    page.locator('#id_time').select_option(value)
