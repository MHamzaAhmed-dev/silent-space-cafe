"""Guest-facing space descriptions keyed by the actual booking identifiers."""
from bookings.models import ReservationRequest

SPACE_DETAILS = [
    {'zone': ReservationRequest.Zone.QUIET, 'name': ReservationRequest.Zone.QUIET.label,
     'copy': 'Sink into a soft seat and take your coffee slowly.',
     'image': 'images/editorial/quiet-corner.webp',
     'alt': 'Olive armchair beside a coffee table, a book and a brass reading lamp'},
    {'zone': ReservationRequest.Zone.READING, 'name': ReservationRequest.Zone.READING.label,
     'copy': 'Bring a book or pick one from our shelves.',
     'image': 'images/editorial/reading-zone.webp',
     'alt': 'Sunlit bookshelves beside a wooden reading table and comfortable chairs'},
    {'zone': ReservationRequest.Zone.SOLO, 'name': ReservationRequest.Zone.SOLO.label,
     'copy': 'A desk for one, with room for your laptop and a little focus.',
     'image': 'images/editorial/solo-space.webp',
     'alt': 'Individual wooden work pod with a laptop, notebook and olive chair'},
]
