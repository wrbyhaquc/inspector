"""Multi-head screen model: one shared backbone looks at the whole frame, one small head per state.

The heads keep the spatial layout of the feature map (no global average pooling): every state lives at a fixed
place on the screen layout, so a head can learn *where* to look (a button, a line of text) as well as *what* it sees."""
import torch
import torch.nn as nn
import torchvision

MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)


class Head(nn.Module):
    def __init__(self, in_ch, grid, out, reduce=32, dropout=0.2):
        super().__init__()
        self.reduce = nn.Sequential(nn.Conv2d(in_ch, reduce, 1), nn.BatchNorm2d(reduce), nn.ReLU(inplace=True))
        self.fc = nn.Sequential(nn.Flatten(), nn.Dropout(dropout), nn.Linear(reduce * grid[0] * grid[1], out))

    def forward(self, x):
        return self.fc(self.reduce(x))


class ScreenModel(nn.Module):
    def __init__(self, heads, size, pretrained=False, backbone="resnet18"):
        super().__init__()
        self.head_specs = heads
        weights = "IMAGENET1K_V1" if pretrained else None
        net = getattr(torchvision.models, backbone)(weights=weights)
        self.backbone = nn.Sequential(net.conv1, net.bn1, net.relu, net.maxpool, net.layer1, net.layer2, net.layer3, net.layer4)
        with torch.no_grad():
            f = self.backbone(torch.zeros(1, 3, size[1], size[0]))
        ch, grid = f.shape[1], tuple(f.shape[2:])
        self.heads = nn.ModuleDict({h["id"]: Head(ch, grid, len(h["classes"]) if h["kind"] == "class" else 1) for h in heads})
        self.register_buffer("mean", torch.tensor(MEAN).view(1, 3, 1, 1))
        self.register_buffer("std", torch.tensor(STD).view(1, 3, 1, 1))

    def forward(self, x):
        """x: uint8 or float in [0, 255], N x 3 x H x W -> {head id: logits (class) or ratio in [0, 1]}"""
        x = (x.float() / 255.0 - self.mean) / self.std
        f = self.backbone(x)
        out = {}
        for h in self.head_specs:
            y = self.heads[h["id"]](f)
            out[h["id"]] = y if h["kind"] == "class" else torch.sigmoid(y.squeeze(1))
        return out


def load(path, device="cpu"):
    """Checkpoint -> (model in eval mode, checkpoint dict with heads / size / schema version)."""
    ck = torch.load(path, map_location=device, weights_only=False)
    m = ScreenModel(ck["heads"], tuple(ck["size"]), pretrained=False, backbone=ck.get("backbone", "resnet18"))
    m.load_state_dict(ck["state_dict"])
    return m.to(device).eval(), ck
