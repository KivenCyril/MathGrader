from abc import ABC, abstractmethod
from typing import Dict, Any


class Agent(ABC):
    """
    Base Agent abstraction.
    """

    @abstractmethod
    def act(self, state: Dict[str, Any], enable_tools: bool = False) -> Dict[str, Any]:
        """
        Execute agent logic and return a structured result.
        """
        raise NotImplementedError
