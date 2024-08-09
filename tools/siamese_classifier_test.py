import os
import sys
import argparse
import numpy as np
from tqdm import tqdm
from pathlib import Path

import torch
import torch.nn as nn
from torchvision import models, transforms

# Add parent dir to path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from utils.config import load_config
from dataset import PairwiseHolographyImageFolder


class SiameseResNet(nn.Module):
    def __init__(self, base_model, num_out):
        super(SiameseResNet, self).__init__()
        self.base_model = base_model
        self.fc = nn.Linear(base_model.fc.out_features * 2, num_out)  # Adjust the input size for the combined features

    def forward(self, input1, input2):
        feat1 = self.base_model(input1)
        feat2 = self.base_model(input2)
        combined_features = torch.cat((feat1, feat2), dim=1)
        output = self.fc(combined_features)
        return output

def test(config_path):
    try:
        # Device configuration
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

        # Load the configuration for testing
        config = load_config(config_path)
        model_config = config["model"]
        dataset_config = config["dataset_params"]
        test_config = config["testing"]

        # create checkpoint directory
        output_dir = test_config["output_dir"]
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Dataset transformations
        transforms_list = [
            transforms.ToTensor(),
            transforms.Resize((dataset_config["img_interpolation"], dataset_config["img_interpolation"]),
                              interpolation=transforms.InterpolationMode.BILINEAR),
            transforms.Normalize([0.5] * dataset_config["img_channels"], [0.5] * dataset_config["img_channels"]),
            transforms.Lambda(lambda x: x.repeat(3, 1, 1))  # Convert 1 channel to 3 channels
        ]
        transform = transforms.Compose(transforms_list)

        # Test dataset
        test_dataset = PairwiseHolographyImageFolder(root=dataset_config["img_path"], 
                                             transform=transform, 
                                             config=dataset_config,
                                             labels=dataset_config.get("labels_test"))

        test_loader = torch.utils.data.DataLoader(dataset=test_dataset, 
                                                  batch_size=test_config["batch_size"], 
                                                  shuffle=False)

       
        # Load the model
        base_model = models.resnet18(pretrained=True)
        num_out = model_config["out_classes"]
        model = SiameseResNet(base_model, num_out)
        model = model.to(device)

        # Load the saved model weights
        model.load_state_dict(torch.load(test_config["model_ckpt"]))
        model.eval()

        # Metrics
        all_labels = []
        all_preds = []
        
        with torch.no_grad():

            for inputs, labels, test in tqdm(test_loader):

                inputs1, inputs2 = inputs
                labels, _ = labels["class"]

                inputs1, inputs2 = inputs1.to(device), inputs2.to(device)
                labels = labels.to(device)

                # Forward pass through the Siamese network
                outputs = model(inputs1, inputs2)
                _, preds = torch.max(outputs.data, 1)
                all_labels.extend(labels.cpu().numpy())
                all_preds.extend(preds.cpu().numpy())

        # Save the labels and predictions to npy files
        np.save(os.path.join(output_dir, 'labels.npy'), np.array(all_labels))
        np.save(os.path.join(output_dir, 'predictions.npy'), np.array(all_preds))

    except Exception as e:
        print(f"Error during testing: {e}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Arguments for resnet testing')
    parser.add_argument('--config', dest='config_path', default='config/siamese_config.yaml', type=str)
    args = parser.parse_args()

    test(args.config_path)
