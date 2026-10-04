import { useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuthState } from "@/auth/context";

export function LoginPage() {
  const { isAuthenticated, signin } = useAuthState();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const returnTo = searchParams.get("returnTo") ?? undefined;

  useEffect(() => {
    if (isAuthenticated) navigate(returnTo ?? "/", { replace: true });
  }, [isAuthenticated, navigate, returnTo]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <CardTitle className="text-xl tracking-tight">Vocal Coach</CardTitle>
          <CardDescription>
            Sign in to review your recordings and track how your speaking improves over time.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button className="w-full" onClick={() => void signin(returnTo)}>
            Sign in with Keycloak
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
