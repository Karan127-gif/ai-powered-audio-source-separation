import torch
import torch.nn as nn
import torch.nn.functional as F

class MultiStemUNet(nn.Module):
    def __init__(self, out_channels=4):
        super(MultiStemUNet, self).__init__()
        self.num_stems = out_channels
        
        # Encoder: 2 Input Channels (Stereo Left/Right)
        self.enc1 = self.conv_block(2, 32)   
        self.enc2 = self.conv_block(32, 64)  
        self.enc3 = self.conv_block(64, 128) 
        self.enc4 = self.conv_block(128, 256)

        # Bridge with Dropout 
        self.bridge = nn.Sequential(
            nn.Conv2d(256, 512, kernel_size=3, padding=1),
            nn.BatchNorm2d(512),
            nn.ReLU(inplace=True),
            nn.Dropout2d(p=0.3) 
        )

        # Decoder with Skip Connections
        self.up3 = self.upconv_block(512, 256)
        self.dec3 = self.conv_block(512, 256, pool=False)
        self.up2 = self.upconv_block(256, 128)
        self.dec2 = self.conv_block(256, 128, pool=False)
        self.up1 = self.upconv_block(128, 64)
        self.dec1 = self.conv_block(128, 64, pool=False)

        self.final_up = self.upconv_block(64, 32)
        self.final_dec = self.conv_block(64, 32, pool=False)
        
        # Output: 8 channels (L/R for each of the 4 stems)
        self.final_conv = nn.Conv2d(32, out_channels * 2, kernel_size=1)

    def conv_block(self, in_c, out_c, pool=True):
        layers = [
            nn.Conv2d(in_c, out_c, kernel_size=3, padding=1),
            nn.BatchNorm2d(out_c),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_c, out_c, kernel_size=3, padding=1),
            nn.BatchNorm2d(out_c),
            nn.ReLU(inplace=True)
        ]
        if pool: return nn.Sequential(*layers, nn.MaxPool2d(2))
        return nn.Sequential(*layers)

    def upconv_block(self, in_c, out_c):
        return nn.ConvTranspose2d(in_c, out_c, kernel_size=2, stride=2)

    def forward(self, x):
        # Encoder
        e1_feat = self.enc1[:-1](x); e1 = self.enc1[-1](e1_feat)
        e2_feat = self.enc2[:-1](e1); e2 = self.enc2[-1](e2_feat)
        e3_feat = self.enc3[:-1](e2); e3 = self.enc3[-1](e3_feat)
        e4_feat = self.enc4[:-1](e3); e4 = self.enc4[-1](e4_feat)

        # Bridge
        b = self.bridge(e4)

        # Decoder
        d3 = self.up3(b); d3 = F.interpolate(d3, size=e4_feat.shape[2:])
        d3 = torch.cat([d3, e4_feat], dim=1); d3 = self.dec3(d3)
        
        d2 = self.up2(d3); d2 = F.interpolate(d2, size=e3_feat.shape[2:])
        d2 = torch.cat([d2, e3_feat], dim=1); d2 = self.dec2(d2)
        
        d1 = self.up1(d2); d1 = F.interpolate(d1, size=e2_feat.shape[2:])
        d1 = torch.cat([d1, e2_feat], dim=1); d1 = self.dec1(d1)

        f = self.final_up(d1); f = F.interpolate(f, size=e1_feat.shape[2:])
        f = torch.cat([f, e1_feat], dim=1); f = self.final_dec(f)

        # Masking
        out = self.final_conv(f)
        out = F.interpolate(out, size=(x.shape[2], x.shape[3]), mode='bilinear')
        
        # Softmax Ratio Masking
        masks = torch.softmax(out.view(x.shape[0], self.num_stems, 2, x.shape[2], x.shape[3]), dim=1)
        return masks * x.unsqueeze(1)