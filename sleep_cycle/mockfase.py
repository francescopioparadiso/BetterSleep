from PhaseManager import  PhaseManager
from datetime import datetime, timedelta
class MockPhaseManager(PhaseManager):
    """A mock PhaseManager that allows time manipulation for testing."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fake_time = datetime(2024, 1, 1, 20, 0)  # Start at 8:00 PM

    def get_current_time(self):
        return self.fake_time

    def fast_forward(self, minutes):
        self.fake_time += timedelta(minutes=minutes)
