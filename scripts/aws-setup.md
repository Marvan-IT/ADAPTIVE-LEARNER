# ADA — AWS Infrastructure Setup

One-time steps to wire S3 → SQS → EC2 pipeline automation and CD deployment.
Run these in order. All AWS CLI commands assume your credentials are configured
(`aws configure` or an IAM instance profile with admin rights on the setup machine).

---

## 1. S3 Bucket

```bash
# Create the bucket (choose the same region as your EC2 instance)
aws s3api create-bucket \
  --bucket ada-books-pdfs \
  --region us-east-1

# Block all public access (PDFs are private)
aws s3api put-public-access-block \
  --bucket ada-books-pdfs \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
```

### Folder structure

Upload PDFs using the `{BOOK_CODE}/` prefix. Supported book codes:

| Book Code   | Book Slug              |
|-------------|------------------------|
| PREALG      | prealgebra             |
| ELEMALG     | elementary_algebra     |
| INTERALG    | intermediate_algebra   |
| COLALG      | college_algebra        |
| COLALGCRQ   | college_algebra_coreq  |
| ALGTRIG     | algebra_trigonometry   |
| PRECALC     | precalculus            |
| CALC1       | calculus_1             |
| CALC2       | calculus_2             |
| CALC3       | calculus_3             |
| INSTATS     | intro_statistics       |
| STATS       | statistics             |
| BUSTATS     | business_statistics    |
| CONTMATH    | contemporary_math      |
| PDS         | principles_data_science|
| ALG1        | algebra_1              |

Example upload:
```bash
aws s3 cp Algebra1.pdf s3://ada-books-pdfs/ALG1/Algebra1.pdf
```

---

## 2. SQS Queue

```bash
# Create standard queue (not FIFO — order is handled by the poller)
aws sqs create-queue \
  --queue-name ada-pipeline-queue \
  --region us-east-1

# Save the queue URL and ARN for the next steps
QUEUE_URL=$(aws sqs get-queue-url \
  --queue-name ada-pipeline-queue \
  --query QueueUrl --output text)

QUEUE_ARN=$(aws sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names QueueArn \
  --query Attributes.QueueArn --output text)

echo "Queue URL: $QUEUE_URL"
echo "Queue ARN: $QUEUE_ARN"
```

---

## 3. SQS Access Policy (allow S3 to publish)

```bash
BUCKET_ARN="arn:aws:s3:::ada-books-pdfs"

aws sqs set-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attributes "{
    \"Policy\": \"{\\\"Version\\\":\\\"2012-10-17\\\",\\\"Statement\\\":[{\\\"Sid\\\":\\\"AllowS3Publish\\\",\\\"Effect\\\":\\\"Allow\\\",\\\"Principal\\\":{\\\"Service\\\":\\\"s3.amazonaws.com\\\"},\\\"Action\\\":\\\"SQS:SendMessage\\\",\\\"Resource\\\":\\\"$QUEUE_ARN\\\",\\\"Condition\\\":{\\\"ArnLike\\\":{\\\"aws:SourceArn\\\":\\\"$BUCKET_ARN\\\"}}}]}\"
  }"
```

Or paste this policy in the AWS Console under SQS > ada-pipeline-queue > Access Policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowS3Publish",
      "Effect": "Allow",
      "Principal": { "Service": "s3.amazonaws.com" },
      "Action": "SQS:SendMessage",
      "Resource": "<QUEUE_ARN>",
      "Condition": {
        "ArnLike": {
          "aws:SourceArn": "arn:aws:s3:::ada-books-pdfs"
        }
      }
    }
  ]
}
```

---

## 4. S3 Event Notification (S3 → SQS)

In the AWS Console:
1. Go to S3 > ada-books-pdfs > Properties > Event notifications
2. Click "Create event notification"
3. Set:
   - **Event name**: `NewPDFUploaded`
   - **Event types**: `s3:ObjectCreated:*`
   - **Prefix**: _(leave blank — trigger on all objects)_
   - **Suffix**: `.pdf`
   - **Destination**: SQS queue — `ada-pipeline-queue`
4. Save

Or via CLI (requires the queue ARN configured in step 3 first):

```bash
aws s3api put-bucket-notification-configuration \
  --bucket ada-books-pdfs \
  --notification-configuration "{
    \"QueueConfigurations\": [
      {
        \"Id\": \"NewPDFUploaded\",
        \"QueueArn\": \"$QUEUE_ARN\",
        \"Events\": [\"s3:ObjectCreated:*\"],
        \"Filter\": {
          \"Key\": {
            \"FilterRules\": [
              { \"Name\": \"suffix\", \"Value\": \".pdf\" }
            ]
          }
        }
      }
    ]
  }"
```

---

## 5. EC2 IAM Instance Profile

### 5a. Create the IAM policy

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws iam create-policy \
  --policy-name ADA-Pipeline-Policy \
  --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [
      {
        \"Sid\": \"S3DownloadPDFs\",
        \"Effect\": \"Allow\",
        \"Action\": \"s3:GetObject\",
        \"Resource\": \"arn:aws:s3:::ada-books-pdfs/*\"
      },
      {
        \"Sid\": \"SQSConsumeMessages\",
        \"Effect\": \"Allow\",
        \"Action\": [
          \"sqs:ReceiveMessage\",
          \"sqs:DeleteMessage\",
          \"sqs:GetQueueAttributes\"
        ],
        \"Resource\": \"$QUEUE_ARN\"
      }
    ]
  }"
```

### 5b. Create the IAM role and instance profile

```bash
# Create role with EC2 trust policy
aws iam create-role \
  --role-name ADA-EC2-Role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": { "Service": "ec2.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }]
  }'

# Attach the pipeline policy
aws iam attach-role-policy \
  --role-name ADA-EC2-Role \
  --policy-arn "arn:aws:iam::$ACCOUNT_ID:policy/ADA-Pipeline-Policy"

# Create instance profile and add the role
aws iam create-instance-profile --instance-profile-name ADA-EC2-Profile
aws iam add-role-to-instance-profile \
  --instance-profile-name ADA-EC2-Profile \
  --role-name ADA-EC2-Role
```

### 5c. Attach profile to your EC2 instance

In the AWS Console:
1. Go to EC2 > Instances > select your ADA instance
2. Actions > Security > Modify IAM Role
3. Select `ADA-EC2-Profile`
4. Save

Or via CLI:
```bash
INSTANCE_ID="i-xxxxxxxxxxxx"  # replace with your EC2 instance ID
aws ec2 associate-iam-instance-profile \
  --instance-id "$INSTANCE_ID" \
  --iam-instance-profile Name=ADA-EC2-Profile
```

Once the profile is attached, boto3 on the EC2 instance will automatically use
the role credentials — no access keys needed in `.pipeline.env`.

---

## 6. Deploy the systemd service on EC2

SSH into the EC2 instance, then:

### 6a. Install Python dependencies

```bash
pip3 install boto3 requests
```

### 6b. Create the environment file

```bash
cat > /home/ubuntu/ADA/scripts/.pipeline.env << 'EOF'
ADA_SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/<ACCOUNT_ID>/ada-pipeline-queue
ADA_S3_BUCKET=ada-books-pdfs
ADA_API_SECRET_KEY=<same value as backend API_SECRET_KEY>
ADA_PROJECT_PATH=/home/ubuntu/ADA
EOF

chmod 600 /home/ubuntu/ADA/scripts/.pipeline.env
```

Do NOT commit `.pipeline.env` to git. It is listed in `.gitignore` via the `scripts/*.env` rule.
Add that rule if it is not already present:

```bash
echo 'scripts/*.env' >> /home/ubuntu/ADA/.gitignore
```

### 6c. Install and start the service

```bash
sudo cp /home/ubuntu/ADA/scripts/ada-pipeline.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ada-pipeline
sudo systemctl start ada-pipeline
sudo systemctl status ada-pipeline
```

### 6d. Verify logs

```bash
# Follow live logs
journalctl -u ada-pipeline -f

# Last 50 lines
journalctl -u ada-pipeline -n 50
```

---

## 7. Required GitHub Secrets

Set these in the repository under Settings > Secrets and variables > Actions:

| Secret | Value |
|---|---|
| `EC2_HOST` | Public IP or hostname of the EC2 instance (e.g. `54.123.45.67`) |
| `EC2_USER` | SSH username — typically `ubuntu` for Ubuntu AMIs |
| `EC2_SSH_KEY` | Full content of the private SSH key (PEM format, no passphrase) |
| `EC2_PROJECT_PATH` | Absolute path to the ADA directory (e.g. `/home/ubuntu/ADA`) |

The `EC2_SSH_KEY` value should be the raw text of the `.pem` file including the
`-----BEGIN RSA PRIVATE KEY-----` header and footer lines.

---

## Verification checklist

After completing setup, verify end-to-end:

1. Upload a test PDF to the bucket:
   ```bash
   aws s3 cp test.pdf s3://ada-books-pdfs/PREALG/test.pdf
   ```
2. Watch the service log on EC2:
   ```bash
   journalctl -u ada-pipeline -f
   ```
   You should see: SQS receive → S3 download → pipeline Stage 1 → Stage 2 → hot-reload → message deleted.
3. Confirm the CI deploy job runs on the next push to `main` in the GitHub Actions tab.
