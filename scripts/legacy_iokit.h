/*
 * Minimal IOCFPlugIn declarations for modern macOS CLT SDKs
 * (IOKit/IOCFPlugIn/IOCFPlugIn.h is no longer shipped).
 */
#ifndef BX_LEGACY_IOKIT_H
#define BX_LEGACY_IOKIT_H

#include <CoreFoundation/CFPlugInCOM.h>
#include <IOKit/IOKitLib.h>

#ifndef DECLARE_UNKNOWNNAMESTRUCT
#define DECLARE_UNKNOWNNAMESTRUCT(name) \
    typedef struct name##Struct { IUNKNOWN_C_GUTS; } name
#endif

DECLARE_UNKNOWNNAMESTRUCT(IOCFPlugInInterface);

EXTERN_C_BEGIN
kern_return_t IOCreatePlugInInterfaceForService(
    io_service_t service,
    CFUUIDRef pluginType,
    CFUUIDRef interfaceType,
    IOCFPlugInInterface ***theInterface,
    SInt32 *score);
EXTERN_C_END

#ifndef kIOCFPlugInInterfaceID
#define kIOCFPlugInInterfaceID                                                \
    CFUUIDGetConstantUUIDWithBytes(NULL, 0xC2, 0x44, 0xE8, 0x58, 0x10, 0x9C, \
                                   0x11, 0xD4, 0x91, 0xD4, 0x00, 0x50, 0xE4, \
                                   0xC6, 0x42, 0x6F)
#endif

#endif /* BX_LEGACY_IOKIT_H */
