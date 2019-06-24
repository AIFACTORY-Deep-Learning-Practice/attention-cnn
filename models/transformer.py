import torch
import torch.nn as nn
from torch.nn.parameter import Parameter

from .bert import BertEncoder, BertConfig

MAX_WIDTH_HEIGHT = 500


class PositionalEncoding2D(nn.Module):
    """Would be more interesting to use sinusoids instead of learning these embeddings
    """

    def __init__(self, d, max_width_height):
        super().__init__()
        self.d = d
        self.max_width_height = max_width_height
        self.embeddings = Parameter(torch.zeros(max_width_height, max_width_height, d))
        self.reset_parameters()

    def reset_parameters(self):
        self.embeddings.data.normal_(0.0, 1 / self.d)

    def forward(self, X):
        """X should be NWHC format"""
        batch_size, width, height, _ = X.shape
        return self.embeddings[:width, :height].unsqueeze(0)

    nn.Embedding


class BertImage(nn.Module):
    """
    Wrapper for a Bert encoder
    """

    def __init__(self, config, num_classes):
        super().__init__()
        # hard coded
        num_channels_in = 3
        num_channels_out = 3

        self.hidden_size = config["hidden_size"]
        bert_config = BertConfig.from_dict(config)

        self.upscale = nn.Linear(num_channels_in, self.hidden_size)
        self.positional_encoding = PositionalEncoding2D(self.hidden_size, MAX_WIDTH_HEIGHT)

        self.encoder = BertEncoder(bert_config)
        self.classifier = nn.Linear(self.hidden_size, num_classes)
        self.pixelizer = nn.Linear(self.hidden_size, num_channels_out)
        self.register_buffer("attention_mask", torch.tensor(1.0))

        self.mask_embedding = Parameter(torch.zeros(self.hidden_size))
        self.cls_embedding = Parameter(torch.zeros(self.hidden_size))
        self.reset_parameters()

    def reset_parameters(self):
        self.mask_embedding.data.normal_(mean=0.0, std=0.01)
        self.cls_embedding.data.normal_(mean=0.0, std=0.01)  # TODO no hard coded

    def forward(self, batch_images, batch_mask=None):
        batch_size, num_channels_in, width, height = batch_images.shape

        assert (
            width < self.positional_encoding.max_width_height
            and height < self.positional_encoding.max_width_height
        )

        # reshape from NCHW to NHWC
        batch_images = batch_images.permute(0, 2, 3, 1)

        batch_images = self.upscale(batch_images)

        # replace masked pixel with mask "embedding"
        if batch_mask is not None:
            batch_images[~batch_mask] = self.mask_embedding

        # add positional embedding
        batch_images += self.positional_encoding(batch_images)

        # prepend classification token
        data = torch.cat(
            [
                self.cls_embedding.expand(batch_size, 1, -1),
                batch_images.view(batch_size, -1, self.hidden_size),
            ],
            dim=1,
        )

        representations = self.encoder(
            data, attention_mask=self.attention_mask, output_all_encoded_layers=False  # TODO
        )[0]

        cls_representation = representations[:, 0]
        cls_prediction = self.classifier(cls_representation)

        pix_representation = representations[:, 1:]
        pix_output = self.pixelizer(pix_representation)
        pix_output = pix_output.reshape(batch_size, width, height, -1)
        # back to NCWH format
        pix_output = pix_output.permute(0, 3, 1, 2)

        return cls_prediction, pix_output
