import os
import time
import argparse
import numpy as np

import torch
import torch.nn as nn
from tqdm import tqdm
from torch import optim

# from torch.utils.tensorboard import SummaryWriter

from UNet import UNet
from train_utils import setup_logging, get_data, save_images


class Diffusion:
    def __init__(self, noise_schedule="linear", noise_steps=1000, beta_start=1e-4, beta_end=0.02, img_size=256, device="cuda"):
        self.noise_schedule = noise_schedule
        self.noise_steps = noise_steps
        self.beta_start = beta_start
        self.beta_end = beta_end
        self.img_size = img_size
        self.device = device

        # Noise steps
        self.beta = self.prepare_noise_schedule().to(device)
        # Formula: α = 1 - β
        self.alpha = 1. - self.beta
        # The cumulative sum of α.
        self.alpha_hat = torch.cumprod(self.alpha, dim=0)

    def prepare_noise_schedule(self, s=0.008):
        if self.noise_schedule == "linear":
            # simple linear noise schedule
            beta_t =  torch.linspace(self.beta_start, self.beta_end, self.noise_steps)
        elif self.noise_schedule == "cosine":
            # create cosine noise schedule
            t = torch.arange(self.noise_steps + 1)
            alpha_t = torch.cos(((t / self.noise_steps + s) / (1 + s)) * (np.pi / 2)).pow(2)
            # caluculate betas
            beta_t = 1 - alpha_t[1:] / alpha_t[:-1]
            # clip beta_t at 0.999 to pretenv singularities
            beta_t = beta_t.clamp(max=0.999)
        else:
            raise NotImplementedError(f"'{self.noise_schedule}' schedule is no implemented!")
        
        return beta_t

    def noise_images(self, x, t):
        sqrt_alpha_hat = torch.sqrt(self.alpha_hat[t])[:, None, None, None]
        sqrt_one_minus_alpha_hat = torch.sqrt(1 - self.alpha_hat[t])[:, None, None, None]
        Ɛ = torch.randn_like(x)
        return sqrt_alpha_hat * x + sqrt_one_minus_alpha_hat * Ɛ, Ɛ

    def sample_timesteps(self, n):
        return torch.randint(low=1, high=self.noise_steps, size=(n,))

    def sample(self, model, n):
        print(f"Sampling {n} new images....")
        model.eval()
        with torch.no_grad():
            x = torch.randn((n, 3, self.img_size, self.img_size)).to(self.device)
            for i in tqdm(reversed(range(1, self.noise_steps)), position=0):
                t = (torch.ones(n) * i).long().to(self.device)
                predicted_noise = model(x, t)
                alpha = self.alpha[t][:, None, None, None]
                alpha_hat = self.alpha_hat[t][:, None, None, None]
                beta = self.beta[t][:, None, None, None]
                if i > 1:
                    noise = torch.randn_like(x)
                else:
                    noise = torch.zeros_like(x)
                x = 1 / torch.sqrt(alpha) * (x - ((1 - alpha) / (torch.sqrt(1 - alpha_hat))) * predicted_noise) + torch.sqrt(beta) * noise
        model.train()
        x = (x.clamp(-1, 1) + 1) / 2
        x = (x * 255).type(torch.uint8)
        return x


def main():

    # setup logging
    setup_logging(args.run_name)

    # get device 
    device = args.device
    
    # setup config

    # load model
    # model = get_model().to(device)
    model = UNet(image_size=args.image_size, 
                 num_classes=args.num_classes,
                 device=device,
                 ).to(device)
    
    print(f'Parameters (total): {sum(p.numel() for p in model.parameters()):_d}')
    print(f'Parameters (train): {sum(p.numel() for p in model.parameters() if p.requires_grad):_d}')

    # set optimizer and scheduler
    optimizer = optim.AdamW(model.parameters(), lr=args.lr)

    # get dataloaders
    dataloader = get_data(args)

    mse = nn.MSELoss()

    diffusion = Diffusion(noise_schedule=args.noise_schedule, 
                          img_size=args.image_size, 
                          device=device,
                          )
    
    # logger = SummaryWriter(os.path.join("runs", args.run_name))
    l = len(dataloader)

    for epoch in range(args.epochs):
        print(f"Starting epoch {epoch}:")
        pbar = tqdm(dataloader)
        for i, (images, condition) in enumerate(pbar):
            images = images.to(device)
            condition = condition.to_device()
            t = diffusion.sample_timesteps(images.shape[0]).to(device)
            x_t, noise = diffusion.noise_images(images, t)

            # set propoportion of conditions to zero
            if np.random.random() < 0.1:
                contidion = None

            predicted_noise = model(x_t, t, condition)
            loss = mse(noise, predicted_noise)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            pbar.set_postfix(MSE=loss.item())
            # logger.add_scalar("MSE", loss.item(), global_step=epoch * l + i)

        sampled_images = diffusion.sample(model, n=images.shape[0])
        save_images(sampled_images, os.path.join("results", args.run_name, f"{epoch}.jpg"))
        torch.save(model.state_dict(), os.path.join("models", args.run_name, f"ckpt.pt"))



if __name__ == "__main__":
    # config
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset_path", type=str, default="./data/")
    parser.add_argument("--epochs", type=int, default=500)
    parser.add_argument("--batch_size", type=int, default=8)
    parser.add_argument("--image_size", type=int, default=32)
    parser.add_argument("--noise_schedule", type=str, default="cosine")
    parser.add_argument("--device", type=str, default=('cuda' if torch.cuda.is_available() else 'cpu'))
    parser.add_argument("--num_classes", type=int, default=None)
    args = parser.parse_args()

    args.run_name = f"2d_geometric_shapes_{args.image_size}_{np.round(time.time(), 0)}"

    args.device = "cuda"
    args.lr = 3e-4


    main()