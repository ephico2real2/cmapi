        NamespaceCreate: {
            annotations?: {
                "cmapi.net/protected"?: string;
                readonly "company.net/app-environment"?: string;
                "company.net/mnemonic-confluence"?: string;
                "company.net/mnemonic-group-contact"?: string;
            } & {
                [key: string]: string;
            };
            expiresAt?: string | null;
            justification?: string | null;
            labels: {
                "cmapi.net/protected"?: string;
                readonly "company.net/app-environment"?: string;
                "company.net/cl": "0" | "1" | "2" | "3";
                "company.net/lob": "amgsst";
                "company.net/mnemonic": string;
                readonly name?: string;
            } & {
                [key: string]: string;
            };
            limitRange?: {
                [key: string]: {
                    [key: string]: {
                        [key: string]: string;
                    };
                };
            } | null;
            namespace: string;
            onBehalfOf?: string | null;
            placementId?: string | null;
            quota?: {
                [key: string]: string;
            } | null;
            tier: string;
        };
