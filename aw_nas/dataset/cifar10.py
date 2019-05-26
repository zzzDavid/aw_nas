# -*- coding: utf-8 -*-
from torchvision import (datasets, transforms)

from aw_nas.utils.torch_utils import Cutout
from aw_nas.dataset.base import BaseDataset

class Cifar10(BaseDataset):
    NAME = "cifar10"

    def __init__(self, data_dir="./data", cutout=None):
        super(Cifar10, self).__init__(data_dir)
        self.cutout = cutout

        cifar_mean = [0.49139968, 0.48215827, 0.44653124]
        cifar_std = [0.24703233, 0.24348505, 0.26158768]

        train_transform = transforms.Compose([
            transforms.RandomCrop(32, padding=4),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            transforms.Normalize(cifar_mean, cifar_std),
        ])
        if self.cutout:
            train_transform.transforms.append(Cutout(self.cutout))

        test_transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize(cifar_mean, cifar_std),
        ])

        self.datasets = {}
        self.datasets["train"] = datasets.CIFAR10(root=self.data_dir, train=True,
                                                  download=True, transform=train_transform)
        # temp for debug...
        # self.datasets["train"].data = self.datasets["train"].data[:512]
        self.datasets["test"] = datasets.CIFAR10(root=self.data_dir, train=False,
                                                 download=True, transform=test_transform)

    def splits(self):
        return self.datasets

    def data_type(self):
        return "image"
