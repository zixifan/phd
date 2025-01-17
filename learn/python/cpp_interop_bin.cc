#include "learn/python/cpp_interop.pb.h"
#include "phd/macros.h"
#include "phd/pbutil.h"

void ProcessProtobuf(const AddXandY& input_proto,
                     AddXandY* output_proto) {
  int x = input_proto.x();
  int y = input_proto.y();
  DEBUG("Adding %d and %d and storing the result in a new message", x, y);
  output_proto->set_result(x + y);
}

PBUTIL_PROCESS_MAIN(ProcessProtobuf, AddXandY, AddXandY);
