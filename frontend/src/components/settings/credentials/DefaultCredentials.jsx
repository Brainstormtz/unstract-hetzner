import { Button, Form, Input, Typography } from "antd";
import { useEffect, useState } from "react";

import { useAxiosPrivate } from "../../../hooks/useAxiosPrivate";
import { IslandLayout } from "../../../layouts/island-layout/IslandLayout.jsx";
import { useAlertStore } from "../../../store/alert-store";
import { useSessionStore } from "../../../store/session-store";
import { CustomButton } from "../../widgets/custom-button/CustomButton.jsx";
import { SpinnerLoader } from "../../widgets/spinner-loader/SpinnerLoader.jsx";
import { TopBar } from "../../widgets/top-bar/TopBar.jsx";
import { useExceptionHandler } from "../../../hooks/useExceptionHandler.jsx";
import "./DefaultCredentials.css";

function DefaultCredentials() {
  const axiosPrivate = useAxiosPrivate();
  const { sessionDetails } = useSessionStore();
  const { setAlertDetails } = useAlertStore();
  const handleException = useExceptionHandler();
  const [loading, setLoading] = useState(true);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [form] = Form.useForm();

  const validateMessages = {
    required: "required!",
    types: {
      email: "Enter a valid email!",
    },
  };

  const getDefaultCredentials = async () => {
    setLoading(true);
    const requestOptions = {
      method: "GET",
      url: `/api/v1/unstract/${sessionDetails?.orgId}/credentials/`,
      headers: {
        "X-CSRFToken": sessionDetails?.csrfToken,
        "Content-Type": "application/json",
      },
    };
    axiosPrivate(requestOptions)
      .then((res) => {
        const { username, password } = res?.data || {};
        form.setFieldsValue({
          username,
          password,
        });
      })
      .catch((err) => {
        setAlertDetails(handleException(err, "Failed to load default credentials"));
      })
      .finally(() => {
        setLoading(false);
      });
  };

  const updateDefaultCredentials = async (values) => {
    const requestOptions = {
      method: "POST",
      url: `/api/v1/unstract/${sessionDetails?.orgId}/credentials/update/`,
      data: values,
      headers: {
        "X-CSRFToken": sessionDetails?.csrfToken,
        "Content-Type": "application/json",
      },
    };
    axiosPrivate(requestOptions)
      .then((res) => {
        setAlertDetails({
          type: "success",
          content: "Default credentials updated successfully",
        });
      })
      .catch((err) => {
        setAlertDetails(handleException(err, "Failed to update default credentials"));
      })
      .finally(() => setSubmitLoading(false));
  };

  const onSubmit = (values) => {
    setSubmitLoading(true);
    updateDefaultCredentials(values);
  };

  useEffect(() => {
    getDefaultCredentials();
  }, []);

  return (
    <>
      <TopBar
        enableSearch={false}
        title="Default Credentials"
      />
      <IslandLayout>
        <div className="default-credentials-container">
          {loading ? (
            <div className="loader-container">
              <SpinnerLoader />
            </div>
          ) : (
            <>
              <Typography.Paragraph className="credentials-description">
                Update the default authentication credentials used for accessing the system.
                These credentials are used when no other authentication method is available.
              </Typography.Paragraph>
              <Form
                form={form}
                name="default-credentials-form"
                onFinish={onSubmit}
                validateMessages={validateMessages}
                layout="vertical"
              >
                <Form.Item
                  name="username"
                  label="Username"
                  rules={[{ required: true }]}
                >
                  <Input placeholder="Username" />
                </Form.Item>
                <Form.Item
                  name="password"
                  label="Password"
                  rules={[
                    { required: true },
                    {
                      validator: (_, value) => {
                        if (!value || value.length < 8) {
                          return Promise.reject("Password must be at least 8 characters long");
                        }
                        
                        const hasUppercase = /[A-Z]/.test(value);
                        const hasLowercase = /[a-z]/.test(value);
                        const hasDigit = /\d/.test(value);
                        const hasSpecial = /[^A-Za-z0-9]/.test(value);
                        
                        if (!(hasUppercase && hasLowercase && hasDigit && hasSpecial)) {
                          return Promise.reject(
                            "Password must contain at least one uppercase letter, one lowercase letter, " +
                            "one digit, and one special character"
                          );
                        }
                        
                        return Promise.resolve();
                      },
                    },
                  ]}
                >
                  <Input.Password placeholder="Password" />
                </Form.Item>
                <Form.Item>
                  <div className="credentials-button-container">
                    <Button onClick={() => form.resetFields()}>
                      Reset
                    </Button>
                    <CustomButton
                      type="primary"
                      htmlType="submit"
                      loading={submitLoading}
                    >
                      Update Credentials
                    </CustomButton>
                  </div>
                </Form.Item>
              </Form>
            </>
          )}
        </div>
      </IslandLayout>
    </>
  );
}

export { DefaultCredentials };