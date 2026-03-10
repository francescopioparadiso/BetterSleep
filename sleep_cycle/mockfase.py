from PhaseManager import  PhaseManager
from datetime import datetime, timedelta

class MockPhaseManager(PhaseManager):
    """
    A mock PhaseManager that allows time manipulation for testing.

    This class extends PhaseManager to provide deterministic time control
    during simulations. Instead of using real wall-clock time, it maintains
    a fake_time variable that can be advanced programmatically.

    Attributes:
        fake_time (datetime): Virtual clock time used for phase calculations
    """

    def __init__(self, *args, **kwargs):
        """
        Initialize the mock phase manager with a default starting time.

        Args:
            *args: Positional arguments passed to parent PhaseManager
            **kwargs: Keyword arguments passed to parent PhaseManager
        """
        super().__init__(*args, **kwargs)
        self.fake_time = datetime(2025, 3, 1, 20, 0)  # Start at 8:00 PM

    def get_current_time(self):
        """
        Override parent method to return simulated time instead of real time.

        Returns:
            datetime: The current virtual time for simulation
        """
        return self.fake_time

    def fast_forward(self, minutes):
        """
        Advance the virtual clock by a specified number of minutes.

        This allows the simulation to compress hours of real time into
        seconds of simulation time for testing purposes.

        Args:
            minutes (int): Number of virtual minutes to advance
        """
        self.fake_time += timedelta(minutes=minutes)
