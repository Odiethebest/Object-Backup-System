# midterm requirement
___
You are asked to build an object backup system, which maintains copies in a destination bucket (call it Bucket Dst) for objects in a the source bucket (call it Bucket Src). In addition, the original object's name and the copy's name are recorded in a DynamoDB table (call it Table T).

The backup system is composed of two lambdas, called Replicator and Cleaner. Replicator is triggered by events in Bucket Src, while Cleaner is periodically triggered, at an interval of 1 minute.

When Replicator is triggered, it checks the incoming event:

- If it is a PUT event, let's say it is for object MyObj, the Replicator creates a copy of MyObj into Bucket Dst. If MyObj already has more than three copies in Bucket Dst, the oldest copy should be deleted while keeping the more recent copies untouched. Otherwise, do not delete any of the copies. In any case, Table T needs to be updated to reflect the mapping between MyObj and the new copy.

- If it is a DELETE event, Replicator marks the item(s) in Table T to indicate that the original object has been deleted and the copies are now disowned. It's up to your design how to mark. But in any case, it does not actually delete the copies. The deletion will be left to the Cleaner.

When Cleaner is triggered, it queries Table T to find out all the copies that have been disowned for longer than 10s and delete all those copies. In addition, it updates Table T so that the deleted copies will not be found by future queries.

Design the Table T (and its indices if needed) in a way that no scan is needed for the tasks above.  Partial credits will be given if scan is used.

Apart from the AWS resources that are already mentioned above, feel free to create any if you feel necessary. But make sure all of them are created by CDK (except for those S3 objects). If any resource is manually created via AWS console, document that in a README file for partial credits. Your CDK should have at least three stacks: one for each lambda plus one for the storage (S3 buckets and DynamoDB table).



Submission:

Submit on GradeScope, your submission should include the lambda handler code and CDK code, in one or more zip files. All the submission should be before 6pm.

Demo steps:

0. Before the demo, use cdk destory to delete all the stacks and the associated resources.
   Deploy the stacks. It's okay to manually upload the lambda code to an S3 bucket.
   Go to the Cloudformation console and show the stacks. TA - please check the stack creation timestamp.
   TA - please check that under the resources tab of the stacks, it collectively show two lambdas, two S3 buckets, one Dynamodb table, one or two eventbridge rules.
   Manually create/delete the following objects in the source bucket.
   Create an object called Assignment1.txt
   Create an object called Assignment2.txt.  TA - please check that there are one copy for each in the destination bucket. Also check the DDB table has records mapping from the origin object to its copy.
   Re-upload the object Assignment1.txt. TA - please check that there are now two copies for assignment1.txt in the destination bucket. Also check the DDB table has records has been updated to point to the new copy.
   Re-upload the object Assignment1.txt.
   Re-upload the object Assignment1.txt. TA - please check that there are only three copies for assignment1.txt in the destination bucket -- the oldest copy is deleted. Also check the DDB table has records has been updated to point to the latest copy.
   Delete Assignment1.txt in the source bucket, wait for more than 10 seconds, then manually invoke the Cleaner lambda. TA - please check that all the copies of assignment1.txt are deleted from the destination bucket.
   Repeat Step 6 for Assignment2.txt.
   Code review
   Please let me know if there's any questions. Thanks!
