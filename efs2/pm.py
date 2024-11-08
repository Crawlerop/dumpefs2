from abc import ABCMeta, abstractmethod
from .super import Superblock
from io import RawIOBase
from .log import PageLog

class PageManager(metaclass=ABCMeta):    
    def __init__(self, sb: Superblock, file: RawIOBase, base_offset: int) -> None:
        self.super: Superblock = sb
        self.file: RawIOBase = file
        self._base_offset: int = base_offset
        self._log: PageLog = None
            
    def compute_ptables(self) -> None:
        pass

    @abstractmethod
    def get_forward(self, cluster: int) -> int:
        pass
    
    @abstractmethod
    def get_reverse(self, page: int) -> int:
        pass

    def forward_to_offset(self, cluster: int) -> int:
        return self.get_forward(cluster) * self.super.page_size

    def forward_seek(self, cluster: int, offset_from_cluster: int=0) -> None:
        self.file.seek(self._base_offset + self.forward_to_offset(cluster) + (offset_from_cluster % self.super.page_size))

    def set_log(self, log: PageLog):
        self._log = log
        
    def __repr__(self):
        return "<{klass} {attrs}>".format(
            klass=self.__class__.__name__,
            attrs=" ".join("{}={!r}".format(k, v) for k, v in self.__dict__.items()),
        )