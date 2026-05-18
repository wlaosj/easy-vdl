# -*- coding: utf-8 -*-
"""Base danmu recorder interface."""
from abc import ABC, abstractmethod


class BaseDanmuRecorder(ABC):
    """Minimal interface for danmu recorders."""

    @property
    @abstractmethod
    def danmu_path(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def danmu_index_path(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def start(self):
        raise NotImplementedError

    @abstractmethod
    def stop(self):
        raise NotImplementedError
