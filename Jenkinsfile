pipeline {  
   agent {  
      label '107.111.157.161'  
   }  
   environment {  
      PASSWORD = 'Welcome@#1234'  
      DOCKER_IMAGE_NAME = 'credsweeper:latest'  
      TRIVY_REPORT_FILE = '/home/test/abilash/trivy/'
      DIR = '/home/test/abilash/credsweeper/CredSweeper/'
   }  
   stages {  
      stage('Build') {  
        steps {  
           sh """  
              cd ${DIR}  
              set +x
              echo ${PASSWORD} | sudo -S docker build --no-cache -f ${DIR}Dockerfile ${DIR} -t ${DOCKER_IMAGE_NAME} 
              set -x
           """  
        }  
      }  
      stage('Scan Docker Image') {  
        steps {  
           script {  
              def formatOption = "--format template --template \"@/usr/local/share/trivy/templates/html.tpl\""              
              sh """
                set +x
                echo ${PASSWORD} | sudo -S trivy image --exit-code 1 $formatOption --no-progress --ignore-unfixed $DOCKER_IMAGE_NAME --timeout 10m --output ${TRIVY_REPORT_FILE}${DOCKER_IMAGE_NAME}-Report.html || true
                set -x
              """  
           }  
           publishHTML(target: [  
              allowMissing: true,  
              alwaysLinkToLastBuild: false,  
              keepAll: true,  
              reportDir: '/home/test/abilash/trivy/',  
              reportFiles: 'Report.html',  
              reportName: 'Docker Scan Report'  
           ])  
        }  
      }  
   }  
}