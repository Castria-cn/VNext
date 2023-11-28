import torch
from queue import Queue

class ObjectQueue:
    def __init__(self, max_size: int):
        self.queue = Queue(max_size)

    def enqueue(self, embed: torch.Tensor):
        if self.queue.full():
            self.dequeue()
        self.queue.put(embed)

    def dequeue(self):
        assert not self.queue.empty(), 'Queue empty!'
        self.queue.get()

    def object_center(self) -> torch.Tensor:
        assert not self.queue.empty(), 'Queue empty!'
        queue_obj = self.queue.queue

        center = torch.zeros_like(queue_obj[0]).to(queue_obj[0])
        for embed in queue_obj:
            center += embed
        
        return center / self.queue.qsize()