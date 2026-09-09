/*
 * BodyMetrix BX2000 — native macOS IOKit USB (same stack as BodyViewPersonal).
 * Build:  clang -framework IOKit -framework CoreFoundation scripts/iokit_bx.m -o scripts/iokit_bx
 * Usage:  ./scripts/iokit_bx init|bx|diagnose
 */
#import <CoreFoundation/CoreFoundation.h>
#import <CoreFoundation/CFPlugInCOM.h>
#import <IOKit/IOKitLib.h>
#import <IOKit/usb/IOUSBLib.h>
#import "legacy_iokit.h"
#import <stdio.h>
#import <stdlib.h>
#import <string.h>
#import <unistd.h>

static const UInt16 kVendorID = 0x04D8;
static const UInt16 kProductID = 0xFBB7;

typedef struct {
    IOUSBInterfaceInterface **iface;
    UInt8 outPipe;
    UInt8 inPipe;
} BxUsb;

static int GetIntProperty(io_service_t device, CFStringRef key) {
    CFTypeRef ref = IORegistryEntryCreateCFProperty(device, key, kCFAllocatorDefault, 0);
    if (!ref) return -1;
    int value = -1;
    if (CFGetTypeID(ref) == CFNumberGetTypeID()) {
        CFNumberGetValue((CFNumberRef)ref, kCFNumberIntType, &value);
    }
    CFRelease(ref);
    return value;
}

static io_service_t FindDevice(void) {
    CFMutableDictionaryRef matching = IOServiceMatching(kIOUSBDeviceClassName);
    if (!matching) return 0;

    io_iterator_t iter = 0;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, matching, &iter) != KERN_SUCCESS) {
        return 0;
    }

    io_service_t device = 0;
    io_service_t candidate = 0;
    while ((candidate = IOIteratorNext(iter)) != 0) {
        int vid = GetIntProperty(candidate, CFSTR(kUSBVendorID));
        int pid = GetIntProperty(candidate, CFSTR(kUSBProductID));
        if (vid == (int)kVendorID && pid == (int)kProductID) {
            device = candidate;
            break;
        }
        IOObjectRelease(candidate);
    }
    IOObjectRelease(iter);
    return device;
}

static int OpenInterface(io_service_t device, BxUsb *usb) {
    memset(usb, 0, sizeof(*usb));

    IOCFPlugInInterface **plugIn = NULL;
    SInt32 score = 0;
    kern_return_t kr = IOCreatePlugInInterfaceForService(
        device, kIOUSBDeviceUserClientTypeID, kIOCFPlugInInterfaceID, &plugIn, &score);
    if (kr != KERN_SUCCESS || !plugIn) {
        fprintf(stderr, "IOCreatePlugInInterfaceForService failed: 0x%x\n", kr);
        return -1;
    }

    IOUSBDeviceInterface **dev = NULL;
    HRESULT res = (*plugIn)->QueryInterface(
        plugIn, CFUUIDGetUUIDBytes(kIOUSBDeviceInterfaceID), (LPVOID *)&dev);
    (*plugIn)->Release(plugIn);
    if (res || !dev) {
        fprintf(stderr, "QueryInterface device failed\n");
        return -1;
    }

    kr = (*dev)->USBDeviceOpen(dev);
    if (kr != KERN_SUCCESS) {
        fprintf(stderr, "USBDeviceOpen failed: 0x%x\n", kr);
        (*dev)->Release(dev);
        return -1;
    }

    kr = (*dev)->SetConfiguration(dev, 1);
    if (kr != KERN_SUCCESS) {
        fprintf(stderr, "SetConfiguration failed: 0x%x\n", kr);
        (*dev)->USBDeviceClose(dev);
        (*dev)->Release(dev);
        return -1;
    }

    IOUSBFindInterfaceRequest request;
    request.bInterfaceClass = kIOUSBFindInterfaceDontCare;
    request.bInterfaceSubClass = kIOUSBFindInterfaceDontCare;
    request.bInterfaceProtocol = kIOUSBFindInterfaceDontCare;
    request.bAlternateSetting = kIOUSBFindInterfaceDontCare;

    io_iterator_t ifaceIter = 0;
    kr = (*dev)->CreateInterfaceIterator(dev, &request, &ifaceIter);
    if (kr != KERN_SUCCESS) {
        fprintf(stderr, "CreateInterfaceIterator failed: 0x%x\n", kr);
        (*dev)->USBDeviceClose(dev);
        (*dev)->Release(dev);
        return -1;
    }

    io_service_t usbInterface = IOIteratorNext(ifaceIter);
    IOObjectRelease(ifaceIter);
    (*dev)->USBDeviceClose(dev);
    (*dev)->Release(dev);

    if (!usbInterface) {
        fprintf(stderr, "No USB interface found\n");
        return -1;
    }

    plugIn = NULL;
    kr = IOCreatePlugInInterfaceForService(
        usbInterface, kIOUSBInterfaceUserClientTypeID, kIOCFPlugInInterfaceID, &plugIn, &score);
    IOObjectRelease(usbInterface);
    if (kr != KERN_SUCCESS || !plugIn) {
        fprintf(stderr, "IOCreatePlugInInterfaceForService (iface) failed: 0x%x\n", kr);
        return -1;
    }

    IOUSBInterfaceInterface **iface = NULL;
    res = (*plugIn)->QueryInterface(
        plugIn, CFUUIDGetUUIDBytes(kIOUSBInterfaceInterfaceID), (LPVOID *)&iface);
    (*plugIn)->Release(plugIn);
    if (res || !iface) {
        fprintf(stderr, "QueryInterface iface failed\n");
        return -1;
    }

    kr = (*iface)->USBInterfaceOpen(iface);
    if (kr != KERN_SUCCESS) {
        fprintf(stderr, "USBInterfaceOpen failed: 0x%x\n", kr);
        (*iface)->Release(iface);
        return -1;
    }

    UInt8 numEndpoints = 0;
    (*iface)->GetNumEndpoints(iface, &numEndpoints);
    usb->iface = iface;
    usb->outPipe = 0;
    usb->inPipe = 0;

    for (UInt8 pipe = 1; pipe <= numEndpoints; pipe++) {
        UInt8 direction = 0, transferType = 0, endpointNumber = 0;
        UInt16 maxPacketSize = 0;
        UInt8 interval = 0;
        (*iface)->GetPipeProperties(
            iface, pipe, &direction, &endpointNumber, &transferType, &maxPacketSize, &interval);
        if (transferType != kUSBBulk) continue;
        if (direction == kUSBOut && usb->outPipe == 0) usb->outPipe = pipe;
        if (direction == kUSBIn && usb->inPipe == 0) usb->inPipe = pipe;
        printf("  pipe %u: %s bulk ep=%u max=%u\n",
               pipe, direction == kUSBIn ? "IN" : "OUT", endpointNumber, maxPacketSize);
    }

    if (!usb->outPipe || !usb->inPipe) {
        fprintf(stderr, "Missing bulk IN/OUT pipes (out=%u in=%u)\n", usb->outPipe, usb->inPipe);
        (*iface)->USBInterfaceClose(iface);
        (*iface)->Release(iface);
        return -1;
    }
    return 0;
}

static void CloseInterface(BxUsb *usb) {
    if (!usb->iface) return;
    (*usb->iface)->USBInterfaceClose(usb->iface);
    (*usb->iface)->Release(usb->iface);
    usb->iface = NULL;
}

static void ConfigurePipes(BxUsb *usb) {
    /* BodyView SetPipeProperties: timeouts 20ms / 50ms on bulk pipes */
    (*usb->iface)->ClearPipeStallBothEnds(usb->iface, usb->outPipe);
    (*usb->iface)->ClearPipeStallBothEnds(usb->iface, usb->inPipe);
}

static void HexDump(const UInt8 *buf, UInt32 len, UInt32 max) {
    UInt32 n = len < max ? len : max;
    for (UInt32 i = 0; i < n; i++) printf("%02x", buf[i]);
    if (len > max) printf("...");
}

static int WriteOut(BxUsb *usb, const UInt8 *data, UInt32 len) {
    return (*usb->iface)->WritePipeTO(usb->iface, usb->outPipe, (void *)data, len, 20, 50);
}

static int ReadIn(BxUsb *usb, UInt8 *buf, UInt32 bufSize, UInt32 *outLen) {
    UInt32 size = bufSize;
    IOReturn kr = (*usb->iface)->ReadPipeTO(usb->iface, usb->inPipe, buf, &size, 50, 500);
    if (kr != kIOReturnSuccess) return (int)kr;
    *outLen = size;
    return 0;
}

static int CmdInit(BxUsb *usb) {
    ConfigurePipes(usb);
    UInt8 buf[128];
    UInt32 got = 0;
    const UInt8 wake[] = {0x01};
    WriteOut(usb, wake, 1);
    usleep(30000);
    if (ReadIn(usb, buf, sizeof(buf), &got) == 0 && got > 0) {
        printf("bulk after OUT 01: %u bytes  ", got);
        HexDump(buf, got, 48);
        printf("\n");
        return 0;
    }
    printf("init OK (pipes armed, no bulk data yet)\n");
    return 0;
}

static int CmdDiagnose(BxUsb *usb) {
    ConfigurePipes(usb);
    UInt8 buf[2048];
    UInt32 got = 0;
    const struct { const char *label; const UInt8 *data; UInt32 len; } outs[] = {
        {"bulk IN (no OUT)", NULL, 0},
        {"OUT 01", (const UInt8[]){0x01}, 1},
        {"OUT 02", (const UInt8[]){0x02}, 1},
        {"OUT a001", (const UInt8[]){0xA0, 0x01}, 2},
        {"OUT 00", (const UInt8[]){0x00}, 1},
    };
    int hits = 0;
    for (size_t i = 0; i < sizeof(outs) / sizeof(outs[0]); i++) {
        ConfigurePipes(usb);
        if (outs[i].data) {
            WriteOut(usb, outs[i].data, outs[i].len);
            usleep(30000);
        }
        got = 0;
        if (ReadIn(usb, buf, sizeof(buf), &got) == 0 && got > 0) {
            printf("  %s: %u bytes  ", outs[i].label, got);
            HexDump(buf, got, 48);
            printf("\n");
            hits++;
        } else {
            printf("  %s: 0 bytes\n", outs[i].label);
        }
    }
    return hits ? 0 : 1;
}

static int CmdBx(BxUsb *usb) {
    ConfigurePipes(usb);
    const UInt8 cmd[] = {0xA0, 0x01};
    UInt8 buf[2048];
    UInt32 best = 0;
    UInt8 bestBuf[2048];

    printf("Hold SEND on gelled skin — listening 30s via IOKit…\n");
    for (int i = 0; i < 150; i++) {
        WriteOut(usb, cmd, sizeof(cmd));
        usleep(200000);
        UInt32 got = 0;
        if (ReadIn(usb, buf, sizeof(buf), &got) == 0 && got > best) {
            best = got;
            memcpy(bestBuf, buf, got);
        }
        if (best >= 32) break;
    }

    printf("Received %u bytes\n", best);
    if (best > 0) {
        printf("Hex: ");
        HexDump(bestBuf, best, 64);
        printf("\n");
        return 0;
    }
    return 1;
}

int main(int argc, char *argv[]) {
    const char *cmd = (argc > 1) ? argv[1] : "bx";
    io_service_t device = FindDevice();
    if (!device) {
        fprintf(stderr, "BodyMetrix probe not found (04D8:FBB7)\n");
        return 1;
    }

    BxUsb usb;
    printf("Found BodyMetrix — opening IOKit interface…\n");
    if (OpenInterface(device, &usb) != 0) {
        IOObjectRelease(device);
        return 1;
    }
    IOObjectRelease(device);

    int rc = 1;
    if (strcmp(cmd, "init") == 0) rc = CmdInit(&usb);
    else if (strcmp(cmd, "diagnose") == 0) rc = CmdDiagnose(&usb);
    else if (strcmp(cmd, "bx") == 0) rc = CmdBx(&usb);
    else {
        fprintf(stderr, "Usage: %s [init|bx|diagnose]\n", argv[0]);
        rc = 1;
    }

    CloseInterface(&usb);
    return rc;
}
