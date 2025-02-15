# Cell 1
import torch
print(f'PyTorch version: {torch.__version__}')

from torch import nn
from torch.utils.data import DataLoader
from torch.amp import autocast, GradScaler

import torchvision
from torchvision.transforms import ToTensor


# Cell 2
if torch.cuda.is_available():
    device = 'cuda'
elif torch.backends.mps.is_available():
    device = 'mps'
else:
    device = 'cpu'
    
print(f'Using device: {device}')


# Cell 3
training_dataset = torchvision.datasets.FashionMNIST(root = 'data', train = True, download = True, transform = ToTensor())
test_dataset = torchvision.datasets.FashionMNIST(root = 'data', train = False, download = True, transform = ToTensor())

mini_batch_size = 64
training_data_loader = DataLoader(training_dataset, batch_size = mini_batch_size, pin_memory = True, shuffle = True)
test_data_loader = DataLoader(test_dataset, batch_size = mini_batch_size, pin_memory = True)

print('-------------------------------')
print(f'Training dataset size:              {len(training_dataset)}')
print(f'Number of training mini-batches:    {len(training_data_loader)}')
print('')
print(f'Test dataset size:                  {len(test_dataset)}')
print(f'Number of test mini-batches:        {len(test_data_loader)}')
for x, t in training_data_loader:
    print('-------------------------------')
    print(f'Shape of input: {x.shape} {x.dtype}')
    print(f'Shape of target: {t.shape} {t.dtype}')
    print('-------------------------------')
    break 


# Cell 4
class NeuralNetwork(nn.Module):
    def parameter_initializer(self, layer):
        if hasattr(layer, 'weight') and hasattr(layer, 'bias'):
            torch.nn.init.xavier_normal_(layer.weight) 
            torch.nn.init.zeros_(layer.bias)
            
    def __init__(self):
        super().__init__()
        
        self.cnn_stack1 = nn.Sequential(
            nn.Conv2d(in_channels = 1, out_channels = 4, kernel_size = 5, stride = 2, padding = 2, padding_mode = 'zeros'),
            nn.GELU(),
            nn.Conv2d(in_channels = 4, out_channels = 8, kernel_size = 5, stride = 2, padding = 1, padding_mode = 'zeros'),
            nn.GELU(),
            nn.Conv2d(in_channels = 8, out_channels = 16, kernel_size = 5, stride = 2, padding = 1, padding_mode = 'zeros'),
            nn.GELU()
        )

        self.cnn_stack2 = nn.Sequential(
            nn.Conv2d(in_channels = 1, out_channels = 4, kernel_size = 5, stride = 2, padding = 2, padding_mode = 'zeros'),
            nn.GELU(),
            nn.Conv2d(in_channels = 4, out_channels = 8, kernel_size = 5, stride = 2, padding = 2, padding_mode = 'zeros'),
            nn.GELU()
        )
        
        self.linear_stack1 = nn.Sequential(
            nn.Flatten(start_dim = 1),
            nn.Linear(16 * 2 * 2, 32)
        )
        
        self.linear_stack2 = nn.Sequential(
            nn.Flatten(start_dim = 1),
            nn.Linear(8 * 7 * 7, 128),
            nn.Tanh(),
            nn.Linear(128, 32)
        )

        self.softmax_stack = nn.Sequential(
            nn.Linear(32, 10),
            nn.Softmax(dim = 1)
        )
        
        for module in self.modules():		
            module.apply(self.parameter_initializer)
        
    @autocast(device_type = device)
    def forward(self, x):
        x1 = self.cnn_stack1(x)
        x1 = self.linear_stack1(x1)

        x2 = self.cnn_stack2(x)
        x2 = self.linear_stack2(x2)

        x = x1 + x2
        y = self.softmax_stack(x)
        
        return y

model = NeuralNetwork().to(device)
model = torch.compile(model, mode = 'reduce-overhead')
optimizer = torch.optim.Adam(model.parameters(), lr = 5e-3, betas = (0.9, 0.999), weight_decay = 1e-4)
scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size = 1, gamma = 0.5)


# Cell 5
def save_checkpoint(model, optimizer, scheduler):
    checkpoint = {
        'model_state'       : model.state_dict(),
        'optimizer_state'   : optimizer.state_dict(),
        'scheduler_state'   : scheduler.state_dict()
    }

    torch.save(checkpoint, 'checkpoint.pth')

def load_checkpoint(model, optimizer, scheduler):
    checkpoint = torch.load('checkpoint.pth', weights_only = False)

    model.load_state_dict(checkpoint['model_state'])
    optimizer.load_state_dict(checkpoint['optimizer_state'])
    scheduler.load_state_dict(checkpoint['scheduler_state'])


# Cell 6
def train(device, data_loader, model, optimizer, accumulation_number = 1):
    total_loss = 0

    model.train()
    scaler = GradScaler()
    for mini_batch_index, (x, t) in enumerate(data_loader):
        x = x.to(device)
        
        y = model(x)
        t = t.to(y.device)
        loss = torch.nn.functional.cross_entropy(y, t)
                
        scaler.scale(loss).backward()

        if mini_batch_index % accumulation_number == 0:
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1e-1)
            scaler.step(optimizer)
            scaler.update()
            optimizer.zero_grad()
        
        mini_batch_size = x.shape[0]
        total_loss += loss.item() * mini_batch_size
    
    dataset_size = len(data_loader.dataset)
    average_loss = total_loss / dataset_size

    return average_loss

def test(device, data_loader, model):
    total_loss = 0
    total_correct = 0

    model.eval()
    with torch.no_grad():
        for x, t in data_loader:
            x = x.to(device)

            y = model(x)
            t = t.to(y.device)
            loss = torch.nn.functional.cross_entropy(y, t)

            mini_batch_size = x.shape[0]
            total_loss += loss.item() * mini_batch_size
            total_correct += (y.argmax(dim = 1) == t).type(torch.float).sum().item()
    
    dataset_size = len(data_loader.dataset)
    average_loss = total_loss / dataset_size
    accuracy = total_correct / dataset_size

    return average_loss, accuracy

def inference(device, data, model):
    x = data.view(1, 1, 28, 28)
    
    model.eval()
    with torch.no_grad():
        x = x.to(device)
        y = model(x)

    return y


# Cell 7
start_event = torch.cuda.Event(enable_timing = True)
end_event = torch.cuda.Event(enable_timing = True)

def initialize_cuda_performace_record():
    torch.cuda.init()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()

    start_event.record()
    
def get_cuda_performace_record():
    end_event.record()
    
    torch.cuda.synchronize()
    excution_time = start_event.elapsed_time(end_event) / 1000
    peak_VRAM_usage = torch.cuda.max_memory_allocated()
    
    return excution_time, peak_VRAM_usage

initialize_cuda_performace_record()

current_epoch       = 0
max_epoch           = 10
accumulation_number = 4
checkpoint_interval = 5

import os
if os.path.exists('checkpoint.pth'):
    load_checkpoint(model, optimizer, scheduler)
    current_epoch = scheduler.last_epoch

    print(f'Resuming training from checkpoint at epoch {current_epoch + 1}\n')

for t in range(current_epoch, max_epoch):
    print(f'Epoch {t + 1 :>3d} / {max_epoch}')

    training_loss = train(device, training_data_loader, model, optimizer, accumulation_number)
    scheduler.step()
    print('  Training progress')
    print(f'    Average loss:   {training_loss :>8f}')

    test_loss, test_accuracy = test(device, test_data_loader, model)
    print('  Validation performance')
    print(f'    Average loss:   {test_loss :>8f}')
    print(f'    Accuracy:       {(100 * test_accuracy) :>0.2f}%')

    if t + 1 < max_epoch:
        print()

    if (t + 1) % checkpoint_interval == 0 and (t + 1) != max_epoch:
        save_checkpoint(model, optimizer, scheduler)
        print(f'Saved training checkpoint at {t + 1} epochs to "checkpoint.pth"')
        print()

excution_time, peak_VRAM_usage = get_cuda_performace_record()
print('-------------------------------')
print(f'Training for {max_epoch} epochs:')
print(f'  Execution time:   {excution_time :>0.4} sec')
print(f'  Peak VRAM usage:  {peak_VRAM_usage / (1024 ** 2) :>,.2f} MB')
print('-------------------------------')

torch.save(model.state_dict(), 'model.pth')
print('Saved PyTorch ANN parameters to model.pth')
print('-------------------------------')


# Cell 8
import random

model = NeuralNetwork().to(device)
model = torch.compile(model, mode = 'reduce-overhead')
model.load_state_dict(torch.load('model.pth', weights_only = True))

test_sample_index = random.randint(0, len(test_dataset) - 1)
x, t = test_dataset[test_sample_index][0], test_dataset[test_sample_index][1]

y = inference(device, x, model)

classes = ['T-shirt/top', 'Trouser', 'Pullover', 'Dress', 'Coat', 'Sandal', 'Shirt', 'Sneaker', 'Bag', 'Ankle boot']
predicted, actual = classes[y.argmax(dim = 1)], classes[t]	
print('Random sample inference')
print(f'  Predicted: "{predicted}", Actual: "{actual}"')
print('-------------------------------')