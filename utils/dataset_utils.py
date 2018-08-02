
import numpy as np
from skimage.feature import plot_matches
from skimage.draw import line
from skimage.io import imshow
from matplotlib import pyplot as plt
from .evaluation import *
import torch
import cv2


def save_mean(dataset, device, path):
    mean, std = torch.zeros(3).to(device), torch.zeros(3).to(device)
    for i in range(1):
        print(str(i) + ' / ' + str(len(dataset)))
        video, _, _, _, _ = dataset[i]
        video = video.to(device).view(video.shape[0], video.shape[1], -1)
        mean += video.mean(2).sum(0)
        std += video.std(2).sum(0)
    mean /= dataset.T * len(dataset)
    std /= dataset.T * len(dataset)
    np.save(path, np.array([mean.numpy(), std.numpy()]))


def draw_skeleton(image, coordinates):
    limbs = [(0, 1), (1, 2), (2, 3), (2, 8), (3, 8), (3, 4), (4, 5), (8, 9), (8, 12),
             (8, 13), (10, 11), (11, 12), (12, 13), (6, 7), (6, 13)]

    coordinates = coordinates.astype(np.int)
    for i, j in limbs:
        rr, cc = line(coordinates[i, 0], coordinates[i, 1], coordinates[j, 0], coordinates[j, 1])
        rr, cc = np.clip(rr, 0, image.shape[1] - 1), np.clip(cc, 0, image.shape[0] - 1)
        image[rr, cc] = (0, 255, 0)
    return image


def to_numpy(tensor, scale=1.0, dtype=np.uint8):
    tensor = tensor.detach().mul(scale).numpy().astype(dtype)
    return np.moveaxis(tensor, 0, 2)


def debug_inputs(video, labels, center_map):
    batch_size, n_stages, n_joints = labels.shape[0], labels.shape[1], labels.shape[2]

    center_map = to_numpy(center_map[0, :, :, :], scale=255)
    center_map = cv2.cvtColor(center_map, cv2.COLOR_GRAY2RGB)

    image_size = video.shape[-2]

    for i in range(batch_size):
        for t in range(n_stages):
            current_frame = to_numpy(video[i, t, :, :, :])

            current_label = to_numpy(labels[i, t, :, :, :], scale=255)
            current_label = np.maximum.reduce(current_label, axis=2)
            current_label = np.expand_dims(current_label, 2)
            current_label = cv2.cvtColor(current_label, cv2.COLOR_GRAY2RGB)
            current_label = cv2.resize(current_label, (image_size, image_size))

            inputs = cv2.addWeighted(current_frame, 0.3, current_label, 0.7, 0)
            inputs = cv2.addWeighted(inputs, 0.6, center_map, 0.4, 0)

            imshow(inputs)
            plt.show()


def debug_predictions(video, labels, outputs):
    if video.shape[1] != outputs.shape[1]:
        f_0 = torch.unsqueeze(video[:, 0, :, :, :], 1)
        video = torch.cat([f_0, video], dim=1)

    if labels.shape[1] != outputs.shape[1]:
        l_0 = torch.unsqueeze(labels[:, 0, :, :, :], 1)
        labels = torch.cat([l_0, labels], dim=1)

    batch_size, n_stages, n_joints = labels.shape[0], labels.shape[1], labels.shape[2]

    video = video.detach().numpy().copy().astype(np.uint8)
    video = np.moveaxis(video, 2, 4)

    labels = labels.detach()
    outputs = outputs.detach()

    image_size = video.shape[-2]
    label_size = labels.shape[-2]
    r = image_size / label_size

    for i in range(batch_size):
        batch_gt_coords = get_preds(labels[i, :, :, :, :]).numpy()
        batch_pred_coords = get_preds(outputs[i, :, :, :, :]).numpy()

        for t in range(n_stages):
            frame = video[i, t, :, :, :]
            frame_gt_coords = np.flip(batch_gt_coords[t, :, :] * r, axis=1)
            frame_pred_coords = np.flip(batch_pred_coords[t, :, :] * r, axis=1)

            gt_frame = draw_skeleton(frame.copy(), frame_gt_coords)
            pred_frame = draw_skeleton(frame.copy(), frame_pred_coords)

            fig, ax = plt.subplots(nrows=1, ncols=1)
            plot_matches(ax, gt_frame, pred_frame, frame_gt_coords, frame_pred_coords, np.array([]),
                         keypoints_color='red')
            plt.show()


def gaussian(size, x, y, sigma):
    X, Y = np.mgrid[0:size, 0:size]
    d2 = (X - x) ** 2 + (Y - y) ** 2
    exp = np.exp(-d2 / 2.0 / sigma / sigma)
    exp[exp < 0.01] = 0
    exp[exp > 1] = 1
    return exp


def center_from_joints(size, x, y):
    x_min, x_max = max(0, np.amin(x)), min(size - 1, np.amax(x))
    y_min, y_max = max(0, np.amin(y)), min(size - 1, np.amax(y))
    return x_min + (x_max - x_min) / 2, y_min + (y_max - y_min) / 2


def compute_label_map(x, y, image_size, label_size, sigma, add_background=True):
    if len(x.shape) < 2:
        x = np.expand_dims(x, 0)
        y = np.expand_dims(y, 0)

    r = label_size / image_size
    T, n_joints = x.shape[0], x.shape[1]
    label_map = np.zeros((T, n_joints + int(add_background), label_size, label_size))
    for t in range(T):
        for p in range(n_joints):
            x_center, y_center = x[t, p] * r, y[t, p] * r
            if x_center > 0 and y_center > 0:
                label_map[t, p, :, :] = gaussian(label_size, y_center, x_center, sigma)
            else:
                label_map[t, p, :, :] = np.zeros((label_size, label_size))
    return torch.from_numpy(label_map).float()


def compute_center_map(x, y, image_size, sigma):
    x, y = center_from_joints(image_size, x, y)
    center_map = gaussian(image_size, x, y, sigma)
    center_map = np.expand_dims(center_map, axis=0)
    return torch.from_numpy(center_map).float()
